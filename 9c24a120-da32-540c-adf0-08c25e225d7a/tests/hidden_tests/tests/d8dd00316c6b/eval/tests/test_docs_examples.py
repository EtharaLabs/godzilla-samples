"""Every Pyfun code block in the user documentation (the "Learn Pyfun" lessons, the
educator sessions, README, RATIONALE and the compiler-internals book), run through the CLI.

Blocks that type-check are compiled (exact Python) and, when they print, run (exact
output, the lesson's "Running this prints" contract). Blocks that are deliberately
broken exercise starters are checked (exact diagnostics, the lessons' "the compiler
reports" contract). Expected transcripts were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

DOC_RUN_CASES = [
    {
        'id': 'learn_01_values_and_inference_block1',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let age = 36\n'
                'let pi = 3.14\n'
                'let isAdmin = true\n'
                '\n'
                'print (f"{name} is {age}")\n'
                'print (f"pi is about {pi}")\n'
                'print isAdmin\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_01_values_and_inference_block3',
        "files": {
            'main.pyfun': (
                'let apples = 4\n'
                'let oranges = 3\n'
                'let fruit = apples + oranges\n'
                'print (f"total fruit: {fruit}")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_02_functions_currying_pipes_block1',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                '\n'
                'let inc = add 1\n'
                '\n'
                'let double x = x * 2\n'
                '\n'
                'let result = 5 |> inc |> double\n'
                '\n'
                'print (add 2 3)\n'
                'print (inc 10)\n'
                'print result\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_02_functions_currying_pipes_block3',
        "files": {
            'main.pyfun': (
                'let double x = x + x\n'
                'let triple x = x + x + x\n'
                '\n'
                'let result = 3 |> double |> triple\n'
                'print result\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_03_option_block1',
        "files": {
            'main.pyfun': (
                'let describe s =\n'
                '  match String.toInt s:\n'
                '    case Some n: f"got the number {n}"\n'
                '    case None: "not a number"\n'
                '\n'
                'print (describe "41")\n'
                'print (describe "hello")\n'
                '\n'
                'let ns = [10, 20, 30]\n'
                'let third = Option.withDefault 0 (List.get 2 ns)\n'
                'let missing = Option.withDefault 0 (List.get 9 ns)\n'
                'print third\n'
                'print missing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_03_option_block3',
        "files": {
            'main.pyfun': (
                'let label s =\n'
                '  match String.toInt s:\n'
                '    case Some n: f"number: {n}"\n'
                '    case None: "no number"\n'
                '\n'
                'print (label "7")\n'
                'print (label "nope")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_04_result_block1',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                '\n'
                'let describe s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: f"parsed {n}"\n'
                '    case Error e: f"failed with {e.errorKind}: {e.errorMessage}"\n'
                '\n'
                'print (describe "42")\n'
                'print (describe "oops")\n'
                '\n'
                'let safe = Result.withDefault 0 (try (parseInt "100"))\n'
                'let fallback = Result.withDefault 0 (try (parseInt "bad"))\n'
                'print safe\n'
                'print fallback\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_04_result_block3',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                '\n'
                'let describe s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: f"ok: {n}"\n'
                '    case Error e: f"bad: {e.errorKind}"\n'
                '\n'
                'print (describe "88")\n'
                'print (describe "bad")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_05_adts_and_match_block1',
        "files": {
            'main.pyfun': (
                'type Shape =\n'
                '  | Circle float\n'
                '  | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'print (area (Circle 2.0))\n'
                'print (area (Rect 3.0 4.0))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_05_adts_and_match_block2',
        "files": {
            'main.pyfun': (
                'let describeSign n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case m if m > 0: "positive"\n'
                '    case _: "negative"\n'
                '\n'
                'print (describeSign 5)\n'
                'print (describeSign 0)\n'
                'print (describeSign (0 - 4))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_05_adts_and_match_block4',
        "files": {
            'main.pyfun': (
                'let size n =\n'
                '  match n:\n'
                '    case 1 | 2 | 3: "small"\n'
                '    case _: "big"\n'
                '\n'
                'print (size 2)\n'
                'print (size 9)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_05_adts_and_match_block6',
        "files": {
            'main.pyfun': (
                'type Light =\n'
                '  | Red\n'
                '  | Amber\n'
                '  | Green\n'
                '\n'
                'let action l =\n'
                '  match l:\n'
                '    case Red: "stop"\n'
                '    case Amber: "wait"\n'
                '    case Green: "go"\n'
                '\n'
                'print (action Red)\n'
                'print (action Amber)\n'
                'print (action Green)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_06_records_block1',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let here = Point { x = 3, y = 4 }\n'
                'let moved = { here with x = 10 }\n'
                '\n'
                'print here.x\n'
                'print moved.x\n'
                'print here.x\n'
                'print here\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_06_records_block2',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let name p =\n'
                '  match p:\n'
                '    case Point { x = 0, y = 0 }: "origin"\n'
                '    case Point { x, y }: "elsewhere"\n'
                '\n'
                'print (name (Point { x = 0, y = 0 }))\n'
                'print (name (Point { x = 3, y = 4 }))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_06_records_block4',
        "files": {
            'main.pyfun': (
                'type Account = { name: string, balance: int }\n'
                '\n'
                'let opened = Account { name = "Ada", balance = 0 }\n'
                'let funded = { opened with balance = 100 }\n'
                '\n'
                'print funded.name\n'
                'print funded.balance\n'
                'print opened.balance\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_07_collections_block1',
        "files": {
            'main.pyfun': (
                'let ns = [1, 2, 3, 4, 5]\n'
                '\n'
                'let squares = List.map (fun x -> x * x) ns\n'
                'let bigs = List.filter (fun x -> x > 2) ns\n'
                'let total = List.fold (+) 0 ns\n'
                'let doubled = List.map ((*) 2) ns\n'
                '\n'
                'let third = Option.withDefault 0 (List.get 2 ns)\n'
                'let missing = Option.withDefault 0 (List.get 9 ns)\n'
                '\n'
                'let uniq = Set.ofList [1, 1, 2, 3]\n'
                'let scores = Map.add "ada" 10 Map.empty\n'
                '\n'
                'print squares\n'
                'print bigs\n'
                'print total\n'
                'print doubled\n'
                'print third\n'
                'print missing\n'
                'uniq |> Set.len |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_07_collections_block2',
        "files": {
            'main.pyfun': (
                'let ns = [4, 8, 15, 16, 23]\n'
                '\n'
                'ns\n'
                '|> Seq.ofList\n'
                '|> Seq.map (fun n -> n * n)\n'
                '|> Seq.filter (fun n -> n > 100)\n'
                '|> Seq.take 2\n'
                '|> Seq.toList\n'
                '|> print\n'
                '\n'
                'Seq.initInfinite (fun i -> i * 3) |> Seq.take 4 |> Seq.toList |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_07_collections_block4',
        "files": {
            'main.pyfun': (
                'let ns = [4, 8, 15, 16, 23]\n'
                '\n'
                'let total = List.fold (+) 0 ns\n'
                'let atTen = Option.withDefault 0 (List.get 10 ns)\n'
                '\n'
                'print total\n'
                'print atTen\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_08_tuples_block1',
        "files": {
            'main.pyfun': (
                'let swap p =\n'
                '  match p:\n'
                '    case (a, b): (b, a)\n'
                '\n'
                'let names = ["ada", "alan"]\n'
                'let scores = [10, 9]\n'
                '\n'
                'let line pair =\n'
                '  match pair:\n'
                '    case (name, score): f"{name}: {score}"\n'
                '\n'
                'let lines = List.zip names scores |> List.map line\n'
                '\n'
                'let byName = List.zip names scores |> Map.ofList\n'
                'let adaScore = Option.withDefault 0 (Map.tryFind "ada" byName)\n'
                '\n'
                'print (swap (1, 2))\n'
                'print lines\n'
                'byName |> Map.toList |> print\n'
                'print adaScore\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_08_tuples_block2',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let (name, score) = ("ada", 10)\n'
                'let (first, (second, third)) = (1, (2, 3))\n'
                'let Point { x, y } = Point { x = 3, y = 4 }\n'
                '\n'
                'let swap p =\n'
                '  let (a, b) = p\n'
                '  (b, a)\n'
                '\n'
                'print f"{name} scored {score}"\n'
                'print (first + second + third)\n'
                'print (x * y)\n'
                'print (swap (1, 2))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_08_tuples_block3',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string, points: int }\n'
                '\n'
                'let line (name, score) = f"{name}: {score}"\n'
                'let label (Cell { letter, points }) = f"{letter} is worth {points}"\n'
                '\n'
                'print (line ("ada", 10))\n'
                'print (label (Cell { letter = "Q", points = 10 }))\n'
                'print (List.map line [("ada", 10), ("alan", 9)])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_08_tuples_block5',
        "files": {
            'main.pyfun': (
                'let describe xs =\n'
                '  match xs:\n'
                '    case []: "empty"\n'
                '    case [only]: f"just {only}"\n'
                '    case [first, *mid, last]: f"{first} ... {last}"\n'
                '\n'
                'print (describe [])\n'
                'print (describe [7])\n'
                'print (describe [1, 2, 3, 4])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_08_tuples_block7',
        "files": {
            'main.pyfun': (
                'let names = ["ada", "alan"]\n'
                'let scores = [10, 9]\n'
                '\n'
                'let line pair =\n'
                '  match pair:\n'
                '    case (name, score): f"{name}: {score}"\n'
                '\n'
                'let lines = List.zip names scores |> List.map line\n'
                '\n'
                'lines |> String.join ", " |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_09_typed_holes_block3',
        "files": {
            'main.pyfun': (
                'let scores = Map.add "ada" 10 (Map.add "alan" 9 Map.empty)\n'
                '\n'
                'let report name =\n'
                '  Map.tryFind name scores\n'
                '  |> Option.withDefault 0\n'
                '  |> String.fromInt\n'
                '\n'
                'print (report "ada")\n'
                'print (report "cy")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_10_mutation_block1',
        "files": {
            'main.pyfun': (
                'let checkout price =\n'
                '  let mut total = price\n'
                '  total <- total + 5\n'
                '  total <- total * 2\n'
                '  total\n'
                '\n'
                'print (checkout 10)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_10_mutation_block3',
        "files": {
            'main.pyfun': (
                'let balance start =\n'
                '  let mut acc = start\n'
                '  acc <- acc + 100\n'
                '  acc <- acc - 30\n'
                '  acc <- acc + 50\n'
                '  acc\n'
                '\n'
                'print (balance 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_11_effects_block1',
        "files": {
            'main.pyfun': (
                'let pure total price qty = price * qty\n'
                '\n'
                'let announce price qty =\n'
                '  print (f"total: {total price qty}")\n'
                '\n'
                'announce 12 3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_11_effects_block2',
        "files": {
            'main.pyfun': (
                'let name = input "Your name: "\n'
                'print (f"Hello, {name}")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
        'stdin': 'Ada\n',
    },
    {
        'id': 'learn_11_effects_block4',
        "files": {
            'main.pyfun': (
                'let pure greet name = f"Hello, {name}"\n'
                '\n'
                'print (greet "ada")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block1',
        "files": {
            'main.pyfun': (
                'extern pure mean: List float -> float = statistics.mean\n'
                '\n'
                'let readings = [2.0, 4.0, 9.0]\n'
                '\n'
                'readings |> mean |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block3',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                '\n'
                'extern flush: unit -> unit = sys.stdout.flush\n'
                '\n'
                'print "written"\n'
                'flush ()\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block4',
        "files": {
            'main.pyfun': (
                'extern type Path\n'
                'extern pure toPath: string -> Path = pathlib.Path\n'
                'extern pure suffix: Path -> string = .suffix\n'
                'extern pure withName: Path -> string -> Path = .with_name\n'
                'extern pure asText: Path -> string = builtins.str\n'
                '\n'
                'let renamed = withName (toPath "report.csv") "summary.csv"\n'
                '\n'
                '"report.csv" |> toPath |> suffix |> print\n'
                'renamed |> asText |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block5',
        "files": {
            'main.pyfun': (
                'type Book = { title: string, pages: int }\n'
                '\n'
                'let bookDecoder =\n'
                '  Decode.map2 (fun title pages -> Book { title = title, pages = pages })\n'
                '    (Decode.field "title" Decode.string)\n'
                '    (Decode.field "pages" Decode.int)\n'
                '\n'
                'let describe r =\n'
                '  match r:\n'
                '    case Ok b: f"{b.title}, {b.pages} pages"\n'
                '    case Error e: f"failed ({e.errorKind})"\n'
                '\n'
                'let wellFormed = """{"title": "Dune", "pages": 412}"""\n'
                'let missingField = """{"title": "Dune"}"""\n'
                '\n'
                'wellFormed |> Decode.decodeString bookDecoder |> describe |> print\n'
                'missingField |> Decode.decodeString bookDecoder |> describe |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block6',
        "files": {
            'main.pyfun': (
                'type Player = Ann | Bob\n'
                'type Msg = Hello Player | Move string | Resign\n'
                'type Turn = { player: Player, msg: Msg, score: Option int }\n'
                '\n'
                'let turn = Turn { player = Bob, msg = Move "K11 a QUIZ", score = Some 42 }\n'
                'let wire = Encode.auto turn\n'
                'print wire\n'
                '\n'
                'let describe t = f"{t.player} played {t.msg}"\n'
                '\n'
                'match Decode.decodeString Decode.auto wire:\n'
                '  case Ok back: print (describe back)\n'
                '  case Error e: print f"failed: {e.errorMessage}"\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block7',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern toThread: (unit -> a) -> Async a = asyncio.to_thread\n'
                '\n'
                'let answer =\n'
                '  async {\n'
                '    let! v = toThread (fun _ -> 6 * 7)\n'
                '    return v\n'
                '  }\n'
                '\n'
                'print (runAsync answer)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_12_python_interop_block9',
        "files": {
            'main.pyfun': (
                'type Book = { title: string, pages: int }\n'
                '\n'
                'let bookDecoder =\n'
                '  Decode.map2 (fun title pages -> Book { title = title, pages = pages })\n'
                '    (Decode.field "title" Decode.string)\n'
                '    (Decode.field "pages" Decode.int)\n'
                '\n'
                'let describe r =\n'
                '  match r:\n'
                '    case Ok b: f"{b.title}, {b.pages} pages"\n'
                '    case Error e: f"failed ({e.errorKind}): {e.errorMessage}"\n'
                '\n'
                'let wellFormed = """{"title": "Dune", "pages": 412}"""\n'
                'let missingField = """{"title": "Dune"}"""\n'
                '\n'
                'wellFormed |> Decode.decodeString bookDecoder |> describe |> print\n'
                'missingField |> Decode.decodeString bookDecoder |> describe |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block1',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  match Option.toResult "bad a" (String.toInt a):\n'
                '    case Error e: Error e\n'
                '    case Ok x:\n'
                '      match Option.toResult "bad b" (String.toInt b):\n'
                '        case Error e2: Error e2\n'
                '        case Ok y: Ok (x + y)\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block2',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  result {\n'
                '    let! x = Option.toResult "bad a" (String.toInt a)\n'
                '    let! y = Option.toResult "bad b" (String.toInt b)\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block3',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  option {\n'
                '    let! x = String.toInt a\n'
                '    let! y = String.toInt b\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block4',
        "files": {
            'main.pyfun': (
                'let double s = String.toInt s |> Option.map (fun n -> n * 2)\n'
                '\n'
                'print (double "21")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block5',
        "files": {
            'main.pyfun': (
                'let counts =\n'
                '  seq {\n'
                '    yield 1\n'
                '    yield 2\n'
                '    yield 3\n'
                '  }\n'
                '\n'
                'counts |> Seq.toList |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block6',
        "files": {
            'main.pyfun': (
                'let squares =\n'
                '  seq {\n'
                '    for x in [1, 2, 3]:\n'
                '      let y = x * x\n'
                '      yield y\n'
                '    yield 100\n'
                '  }\n'
                '\n'
                'squares |> Seq.toList |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_13_computation_expressions_block8',
        "files": {
            'main.pyfun': (
                'let multiply a b =\n'
                '  result {\n'
                '    let! x = Option.toResult "not a number" (String.toInt a)\n'
                '    let! y = Option.toResult "not a number" (String.toInt b)\n'
                '    return x * y\n'
                '  }\n'
                '\n'
                'print (multiply "6" "7")\n'
                'print (multiply "6" "nope")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_14_units_of_measure_block1',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure kg\n'
                '\n'
                'measure N = kg m / s^2                # newton, a derived alias\n'
                '\n'
                'let distance = 100.0<m>\n'
                'let elapsed = 10.0<s>\n'
                'let speed = distance / elapsed        # float<m/s>\n'
                'let side = sqrt 16.0<m^2>             # float<m>\n'
                'let force = 6.0<N>                    # a value in newtons\n'
                '\n'
                'print speed\n'
                'print side\n'
                'print force\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_14_units_of_measure_block3',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'let distance = 240.0<m>\n'
                'let elapsed = 30.0<s>\n'
                '\n'
                '# Speed is distance per unit of time.\n'
                'let speed = distance / elapsed\n'
                '\n'
                'print speed\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_15_modules_block1',
        "files": {
            'main.pyfun': (
                'module Geom =\n'
                '  let square x = x * x\n'
                '  let area w h = w * h\n'
                '  let diagSq w h = square w + square h\n'
                '\n'
                'print (Geom.area 4 5)\n'
                'print (Geom.diagSq 3 4)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_15_modules_block5',
        "files": {
            'main.pyfun': (
                'let cToF c = c * 9 // 5 + 32\n'
                'let fToC f = (f - 32) * 5 // 9\n'
                '\n'
                'print (cToF 100)\n'
                'print (fToC 212)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_15_modules_block6',
        "files": {
            'main.pyfun': (
                'module Temp =\n'
                '  let cToF c = c * 9 // 5 + 32\n'
                '  let fToC f = (f - 32) * 5 // 9\n'
                '\n'
                'print (Temp.cToF 100)\n'
                'print (Temp.fToC 212)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_16_capstone_block2',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'type Run = { name: string, distance: float, time: float }\n'
                '\n'
                'let runDecoder =\n'
                '  Decode.map3 (fun n d t -> Run { name = n, distance = d, time = t })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "distance" Decode.float)\n'
                '    (Decode.field "time" Decode.float)\n'
                '\n'
                'let input = """[\n'
                '  {"name": "ada", "distance": 100.0, "time": 20.0},\n'
                '  {"name": "bo", "distance": 140.0, "time": 30.0}\n'
                ']"""\n'
                '\n'
                'let report =\n'
                '  match Decode.decodeString (Decode.list runDecoder) input:\n'
                '    case Ok runs:\n'
                '      let names = runs |> List.map (fun r -> r.name) |> String.join ", "\n'
                '      let dist = runs |> List.fold (fun a r -> a + r.distance * 1.0<m>) 0.0<m>\n'
                '      let time = runs |> List.fold (fun a r -> a + r.time * 1.0<s>) 0.0<s>\n'
                '      let avg = dist / time\n'
                '      f"{names}: average speed {avg} m/s over {List.len runs} runs"\n'
                '    case Error e: f"could not read input ({e.errorKind})"\n'
                '\n'
                'print report\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_17_recursion_block1',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                '\n'
                'print (fact 5)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_17_recursion_block2',
        "files": {
            'main.pyfun': (
                'let isEven n = if n == 0 then true else isOdd (n - 1)\n'
                'let isOdd n = if n == 0 then false else isEven (n - 1)\n'
                '\n'
                'print (isEven 10)\n'
                'print (isOdd 7)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_17_recursion_block3',
        "files": {
            'main.pyfun': (
                'let countDown n acc = if n == 0 then acc else countDown (n - 1) (acc + n)\n'
                '\n'
                'print (countDown 100000 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_17_recursion_block4',
        "files": {
            'main.pyfun': (
                'type Expr =\n'
                '  | Num int\n'
                '  | Add Expr Expr\n'
                '  | Mul Expr Expr\n'
                '\n'
                'let eval e =\n'
                '  match e:\n'
                '    case Num n: n\n'
                '    case Add l r: eval l + eval r\n'
                '    case Mul l r: eval l * eval r\n'
                '\n'
                'let tree = Add (Num 1) (Mul (Num 2) (Num 3))\n'
                '\n'
                'print (eval tree)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_17_recursion_block6',
        "files": {
            'main.pyfun': (
                'type Tree =\n'
                '  | Leaf int\n'
                '  | Branch Tree Tree\n'
                '\n'
                'let total t =\n'
                '  match t:\n'
                '    case Leaf n: n\n'
                '    case Branch l r: total l + total r\n'
                '\n'
                'let sample = Branch (Leaf 1) (Branch (Leaf 2) (Leaf 3))\n'
                '\n'
                'print (total sample)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block1',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let fetchScore =\n'
                '  async {\n'
                '    let! x = async { return 20 }\n'
                '    return x + 1\n'
                '  }\n'
                '\n'
                'print (runAsync fetchScore)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block2',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let roll =\n'
                '  async {\n'
                '    print "rolling"\n'
                '    return 6\n'
                '  }\n'
                '\n'
                'let twice =\n'
                '  async {\n'
                '    let! a = roll\n'
                '    let! b = roll\n'
                '    return a + b\n'
                '  }\n'
                '\n'
                'print (runAsync twice)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block5',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern sleep: float -> Async unit = asyncio.sleep\n'
                '\n'
                'let nap =\n'
                '  async {\n'
                '    do! sleep 0.01\n'
                '    return "rested"\n'
                '  }\n'
                '\n'
                'print (runAsync nap)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block6',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let slow n =\n'
                '  async {\n'
                '    do! Async.sleep 0.01\n'
                '    return n\n'
                '  }\n'
                '\n'
                'let main =\n'
                '  async {\n'
                '    let! xs = Async.parallel [slow 1, slow 2, slow 3]\n'
                '    print xs\n'
                '    let! quick = Async.timeout 0.001 (Async.sleep 1.0)\n'
                '    print quick\n'
                '    let! r = Async.catch (slow 4)\n'
                '    match r:\n'
                '      case Ok n: print f"finished with {n}"\n'
                '      case Error e: print f"failed: {e.errorKind}"\n'
                '    return ()\n'
                '  }\n'
                '\n'
                'runAsync main\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block7',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let worker name =\n'
                '  async {\n'
                '    do! Async.sleep 0.01\n'
                '    print f"{name} done"\n'
                '  }\n'
                '\n'
                'let session =\n'
                '  Task.scope (async {\n'
                '    Task.start (worker "a")\n'
                '    Task.start (worker "b")\n'
                '    return "both joined"\n'
                '  })\n'
                '\n'
                'print (runAsync session)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_18_async_block10',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let combined =\n'
                '  async {\n'
                '    let! a = async { return 10 }\n'
                '    let! b = async { return 20 }\n'
                '    return a + b\n'
                '  }\n'
                '\n'
                'print (runAsync combined)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_19_active_patterns_block1',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                '\n'
                'let parity n =\n'
                '  match n:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                '\n'
                'print (parity 4)\n'
                'print (parity 7)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_19_active_patterns_block2',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                '\n'
                'let clamped n =\n'
                '  match n:\n'
                '    case Positive p: p\n'
                '    case _: 0\n'
                '\n'
                'print (clamped 9)\n'
                'print (clamped (0 - 5))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_19_active_patterns_block3',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                '\n'
                'let lineKind s =\n'
                '  match s:\n'
                '    case Blank: "empty"\n'
                '    case _: "text"\n'
                '\n'
                'print (lineKind "   ")\n'
                'print (lineKind "hi")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_19_active_patterns_block5',
        "files": {
            'main.pyfun': (
                'let (|Hot|_|) c = if c >= 25 then Some c else None\n'
                '\n'
                'let describe c =\n'
                '  match c:\n'
                '    case Hot t: f"hot at {t}"\n'
                '    case _: "not hot"\n'
                '\n'
                'print (describe 30)\n'
                'print (describe 5)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_20_build_your_own_ce_block1',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: f x\n'
                '      case None: None\n'
                '  let return_ x = Some x\n'
                '\n'
                'let addOpt a b =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addOpt (Some 3) (Some 4))\n'
                'print (addOpt (Some 3) None)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_20_build_your_own_ce_block3',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: f x\n'
                '      case None: None\n'
                '  let return_ x = Some x\n'
                '\n'
                'let addThree a b c =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    let! z = c\n'
                '    return x + y + z\n'
                '  }\n'
                '\n'
                'print (addThree (Some 1) (Some 2) (Some 3))\n'
                'print (addThree (Some 1) None (Some 3))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_21_strings_and_numbers_block1',
        "files": {
            'main.pyfun': (
                'let title = String.concat "Hello, " "World"\n'
                'let loud = String.upper title\n'
                'let words = String.split ", " title\n'
                'let csv = String.join "," words\n'
                'let first5 = String.slice 0 5 title\n'
                '\n'
                'print title\n'
                'print loud\n'
                'print words\n'
                'print csv\n'
                'print first5\n'
                'print (Option.withDefault 0 (String.toInt "41"))\n'
                'print (Option.withDefault 0 (String.toInt "x"))\n'
                'print (Option.withDefault 0.0 (String.toFloat "2.5"))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_21_strings_and_numbers_block2',
        "files": {
            'main.pyfun': (
                'print (Format.fixed 2 3.14159)\n'
                'print (Format.thousands 2 1234567.891)\n'
                'print (Format.grouped 1234567)\n'
                'print (Format.percent 1 0.256)\n'
                'print (Format.padLeft 8 " " "42")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_21_strings_and_numbers_block3',
        "files": {
            'main.pyfun': (
                'let who = "Ada"\n'
                'let score = 41\n'
                '\n'
                'let line = f"{who} scored {score} ({String.upper who})"\n'
                'let debug = f"{score=}"\n'
                'let braces = f"{{literal braces}} around {score}"\n'
                'let winPath = r"C:\\Users\\pyfun\\data.csv"\n'
                'let banner = """== pyfun ==\n'
                'a "quoted" word"""\n'
                'let emoji = "hi \\u{1F600}"\n'
                '\n'
                'print line\n'
                'print debug\n'
                'print braces\n'
                'print winPath\n'
                'print banner\n'
                'print (String.len "café")\n'
                'print (String.len emoji)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_21_strings_and_numbers_block4',
        "files": {
            'main.pyfun': (
                'let million = 1_000_000\n'
                'let mask = 0xFF\n'
                'let bits = 0b1010\n'
                'let perm = 0o17\n'
                'let lightSpeed = 3.0e8\n'
                'let tower = 2.0 ** 3.0 ** 2.0\n'
                'let q = 17 // 5\n'
                'let r = 17 % 5\n'
                'let inRange = 0 <= 7 < 10\n'
                '\n'
                'print million\n'
                'print mask\n'
                'print bits\n'
                'print perm\n'
                'print lightSpeed\n'
                'print tower\n'
                'print q\n'
                'print r\n'
                'print inRange\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_21_strings_and_numbers_block6',
        "files": {
            'main.pyfun': (
                'let label raw =\n'
                '  let n = Option.withDefault 0 (String.toInt raw)\n'
                '  f"{raw} parses to {n}"\n'
                '\n'
                'print (label "42")\n'
                'print (label "oops")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_22_opaque_types_block1',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'opaque type Email = string\n'
                '\n'
                'let uid = UserId "u-1001"\n'
                'let contact = Email "ana@example.org"\n'
                '\n'
                'let describe u =\n'
                '  match u:\n'
                '    case UserId s: s\n'
                '\n'
                'uid |> describe |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_22_opaque_types_block3',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                '\n'
                'extern pure shout: UserId -> string = str.upper\n'
                '\n'
                'let uid = UserId "u-1001"\n'
                'let loud = uid |> shout\n'
                'print loud\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_22_opaque_types_block5',
        "files": {
            'main.pyfun': (
                'opaque type OrderId = string\n'
                '\n'
                'let orderLabel o =\n'
                '  match o:\n'
                '    case OrderId s: String.concat "order " s\n'
                '\n'
                '# The id arrives as a plain string from the outside world.\n'
                'let raw = "o-9"\n'
                '\n'
                'let label = orderLabel (OrderId raw)\n'
                '\n'
                'print label\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_23_keyword_arguments_block1',
        "files": {
            'main.pyfun': (
                'extern parseHex: string -> int = int(base = 16)\n'
                '\n'
                'let raw = "ff"\n'
                '\n'
                'raw |> parseHex |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_23_keyword_arguments_block2',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let fromHex s = parseIn s 16\n'
                'let fromBinary s = parseIn s 2\n'
                '\n'
                'let a = "ff"\n'
                'let b = "1011"\n'
                '\n'
                'a |> fromHex |> print\n'
                'b |> fromBinary |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_23_keyword_arguments_block3',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let ff = parseIn "ff"\n'
                '\n'
                'ff 16 |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_23_keyword_arguments_block4',
        "files": {
            'main.pyfun': (
                '# Two externs that differ only in the base each one pins.\n'
                'extern parseHex: string -> int = int(base = 16)\n'
                'extern parseBinary: string -> int = int(base = 2)\n'
                '\n'
                'let hex = "ff"\n'
                'let binary = "1011"\n'
                '\n'
                'hex |> parseHex |> print\n'
                'binary |> parseBinary |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'learn_23_keyword_arguments_block5',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let fromHex s = parseIn s 16\n'
                'let fromBinary s = parseIn s 2\n'
                '\n'
                'let hex = "ff"\n'
                'let binary = "1011"\n'
                '\n'
                'hex |> fromHex |> print\n'
                'binary |> fromBinary |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'readme_block3',
        "files": {
            'main.pyfun': (
                'extern pure mean:  List float -> float = statistics.mean\n'
                'extern pure stdev: List float -> float = statistics.stdev\n'
                '\n'
                'type Summary = { n: int, mean: float, stdev: float }\n'
                '\n'
                'let summarize xs =\n'
                '  Summary { n = List.len xs, mean = mean xs, stdev = stdev xs }\n'
                '\n'
                'let report xs =\n'
                '  let s = summarize xs\n'
                '  f"n={s.n} mean={s.mean} sd={s.stdev}"\n'
                '\n'
                'print (report [1.0, 2.0, 3.0, 4.0])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'readme_block4',
        "files": {
            'main.pyfun': (
                "extern parseInt: string -> int = int          # Python's built-in int()\n"
                '\n'
                'let safe s = Result.withDefault 0 (try (parseInt s))\n'
                'print (safe "42")     # 42\n'
                'print (safe "oops")   # 0   (the ValueError was caught into an Error)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'readme_block12',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'print (area (Circle 2.0))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'internals_06_units_block1',
        "files": {
            'main.pyfun': (
                'measure m\n'
                '\n'
                'let side = sqrt 16.0<m^2>\n'
                '\n'
                'print side\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'internals_readme_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'measure m\n'
                '\n'
                'let shapes = [Circle 2.0, Rect 3.0 4.0]\n'
                'let total = shapes |> List.fold (fun acc s -> acc + area s) 0.0\n'
                'let side = sqrt 16.0<m^2>\n'
                'print (f"total {total}, side {side}")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'introduction_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'let shapes = [Circle 2.0, Rect 3.0 4.0]\n'
                'shapes |> List.fold (fun acc s -> acc + area s) 0.0 |> print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]

DOC_COMPILE_CASES = [
    {
        'id': 'compile__learn_01_values_and_inference_block1',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let age = 36\n'
                'let pi = 3.14\n'
                'let isAdmin = true\n'
                '\n'
                'print (f"{name} is {age}")\n'
                'print (f"pi is about {pi}")\n'
                'print isAdmin\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_01_values_and_inference_block3',
        "files": {
            'main.pyfun': (
                'let apples = 4\n'
                'let oranges = 3\n'
                'let fruit = apples + oranges\n'
                'print (f"total fruit: {fruit}")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_02_functions_currying_pipes_block1',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                '\n'
                'let inc = add 1\n'
                '\n'
                'let double x = x * 2\n'
                '\n'
                'let result = 5 |> inc |> double\n'
                '\n'
                'print (add 2 3)\n'
                'print (inc 10)\n'
                'print result\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_02_functions_currying_pipes_block3',
        "files": {
            'main.pyfun': (
                'let double x = x + x\n'
                'let triple x = x + x + x\n'
                '\n'
                'let result = 3 |> double |> triple\n'
                'print result\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_03_option_block1',
        "files": {
            'main.pyfun': (
                'let describe s =\n'
                '  match String.toInt s:\n'
                '    case Some n: f"got the number {n}"\n'
                '    case None: "not a number"\n'
                '\n'
                'print (describe "41")\n'
                'print (describe "hello")\n'
                '\n'
                'let ns = [10, 20, 30]\n'
                'let third = Option.withDefault 0 (List.get 2 ns)\n'
                'let missing = Option.withDefault 0 (List.get 9 ns)\n'
                'print third\n'
                'print missing\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_03_option_block3',
        "files": {
            'main.pyfun': (
                'let label s =\n'
                '  match String.toInt s:\n'
                '    case Some n: f"number: {n}"\n'
                '    case None: "no number"\n'
                '\n'
                'print (label "7")\n'
                'print (label "nope")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_04_result_block1',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                '\n'
                'let describe s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: f"parsed {n}"\n'
                '    case Error e: f"failed with {e.errorKind}: {e.errorMessage}"\n'
                '\n'
                'print (describe "42")\n'
                'print (describe "oops")\n'
                '\n'
                'let safe = Result.withDefault 0 (try (parseInt "100"))\n'
                'let fallback = Result.withDefault 0 (try (parseInt "bad"))\n'
                'print safe\n'
                'print fallback\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_04_result_block3',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                '\n'
                'let describe s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: f"ok: {n}"\n'
                '    case Error e: f"bad: {e.errorKind}"\n'
                '\n'
                'print (describe "88")\n'
                'print (describe "bad")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_05_adts_and_match_block1',
        "files": {
            'main.pyfun': (
                'type Shape =\n'
                '  | Circle float\n'
                '  | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'print (area (Circle 2.0))\n'
                'print (area (Rect 3.0 4.0))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_05_adts_and_match_block2',
        "files": {
            'main.pyfun': (
                'let describeSign n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case m if m > 0: "positive"\n'
                '    case _: "negative"\n'
                '\n'
                'print (describeSign 5)\n'
                'print (describeSign 0)\n'
                'print (describeSign (0 - 4))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_05_adts_and_match_block4',
        "files": {
            'main.pyfun': (
                'let size n =\n'
                '  match n:\n'
                '    case 1 | 2 | 3: "small"\n'
                '    case _: "big"\n'
                '\n'
                'print (size 2)\n'
                'print (size 9)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_05_adts_and_match_block6',
        "files": {
            'main.pyfun': (
                'type Light =\n'
                '  | Red\n'
                '  | Amber\n'
                '  | Green\n'
                '\n'
                'let action l =\n'
                '  match l:\n'
                '    case Red: "stop"\n'
                '    case Amber: "wait"\n'
                '    case Green: "go"\n'
                '\n'
                'print (action Red)\n'
                'print (action Amber)\n'
                'print (action Green)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_06_records_block1',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let here = Point { x = 3, y = 4 }\n'
                'let moved = { here with x = 10 }\n'
                '\n'
                'print here.x\n'
                'print moved.x\n'
                'print here.x\n'
                'print here\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_06_records_block2',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let name p =\n'
                '  match p:\n'
                '    case Point { x = 0, y = 0 }: "origin"\n'
                '    case Point { x, y }: "elsewhere"\n'
                '\n'
                'print (name (Point { x = 0, y = 0 }))\n'
                'print (name (Point { x = 3, y = 4 }))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_06_records_block4',
        "files": {
            'main.pyfun': (
                'type Account = { name: string, balance: int }\n'
                '\n'
                'let opened = Account { name = "Ada", balance = 0 }\n'
                'let funded = { opened with balance = 100 }\n'
                '\n'
                'print funded.name\n'
                'print funded.balance\n'
                'print opened.balance\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_07_collections_block1',
        "files": {
            'main.pyfun': (
                'let ns = [1, 2, 3, 4, 5]\n'
                '\n'
                'let squares = List.map (fun x -> x * x) ns\n'
                'let bigs = List.filter (fun x -> x > 2) ns\n'
                'let total = List.fold (+) 0 ns\n'
                'let doubled = List.map ((*) 2) ns\n'
                '\n'
                'let third = Option.withDefault 0 (List.get 2 ns)\n'
                'let missing = Option.withDefault 0 (List.get 9 ns)\n'
                '\n'
                'let uniq = Set.ofList [1, 1, 2, 3]\n'
                'let scores = Map.add "ada" 10 Map.empty\n'
                '\n'
                'print squares\n'
                'print bigs\n'
                'print total\n'
                'print doubled\n'
                'print third\n'
                'print missing\n'
                'uniq |> Set.len |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_07_collections_block2',
        "files": {
            'main.pyfun': (
                'let ns = [4, 8, 15, 16, 23]\n'
                '\n'
                'ns\n'
                '|> Seq.ofList\n'
                '|> Seq.map (fun n -> n * n)\n'
                '|> Seq.filter (fun n -> n > 100)\n'
                '|> Seq.take 2\n'
                '|> Seq.toList\n'
                '|> print\n'
                '\n'
                'Seq.initInfinite (fun i -> i * 3) |> Seq.take 4 |> Seq.toList |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_07_collections_block4',
        "files": {
            'main.pyfun': (
                'let ns = [4, 8, 15, 16, 23]\n'
                '\n'
                'let total = List.fold (+) 0 ns\n'
                'let atTen = Option.withDefault 0 (List.get 10 ns)\n'
                '\n'
                'print total\n'
                'print atTen\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_08_tuples_block1',
        "files": {
            'main.pyfun': (
                'let swap p =\n'
                '  match p:\n'
                '    case (a, b): (b, a)\n'
                '\n'
                'let names = ["ada", "alan"]\n'
                'let scores = [10, 9]\n'
                '\n'
                'let line pair =\n'
                '  match pair:\n'
                '    case (name, score): f"{name}: {score}"\n'
                '\n'
                'let lines = List.zip names scores |> List.map line\n'
                '\n'
                'let byName = List.zip names scores |> Map.ofList\n'
                'let adaScore = Option.withDefault 0 (Map.tryFind "ada" byName)\n'
                '\n'
                'print (swap (1, 2))\n'
                'print lines\n'
                'byName |> Map.toList |> print\n'
                'print adaScore\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_08_tuples_block2',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                '\n'
                'let (name, score) = ("ada", 10)\n'
                'let (first, (second, third)) = (1, (2, 3))\n'
                'let Point { x, y } = Point { x = 3, y = 4 }\n'
                '\n'
                'let swap p =\n'
                '  let (a, b) = p\n'
                '  (b, a)\n'
                '\n'
                'print f"{name} scored {score}"\n'
                'print (first + second + third)\n'
                'print (x * y)\n'
                'print (swap (1, 2))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_08_tuples_block3',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string, points: int }\n'
                '\n'
                'let line (name, score) = f"{name}: {score}"\n'
                'let label (Cell { letter, points }) = f"{letter} is worth {points}"\n'
                '\n'
                'print (line ("ada", 10))\n'
                'print (label (Cell { letter = "Q", points = 10 }))\n'
                'print (List.map line [("ada", 10), ("alan", 9)])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_08_tuples_block5',
        "files": {
            'main.pyfun': (
                'let describe xs =\n'
                '  match xs:\n'
                '    case []: "empty"\n'
                '    case [only]: f"just {only}"\n'
                '    case [first, *mid, last]: f"{first} ... {last}"\n'
                '\n'
                'print (describe [])\n'
                'print (describe [7])\n'
                'print (describe [1, 2, 3, 4])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_08_tuples_block7',
        "files": {
            'main.pyfun': (
                'let names = ["ada", "alan"]\n'
                'let scores = [10, 9]\n'
                '\n'
                'let line pair =\n'
                '  match pair:\n'
                '    case (name, score): f"{name}: {score}"\n'
                '\n'
                'let lines = List.zip names scores |> List.map line\n'
                '\n'
                'lines |> String.join ", " |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_09_typed_holes_block3',
        "files": {
            'main.pyfun': (
                'let scores = Map.add "ada" 10 (Map.add "alan" 9 Map.empty)\n'
                '\n'
                'let report name =\n'
                '  Map.tryFind name scores\n'
                '  |> Option.withDefault 0\n'
                '  |> String.fromInt\n'
                '\n'
                'print (report "ada")\n'
                'print (report "cy")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_10_mutation_block1',
        "files": {
            'main.pyfun': (
                'let checkout price =\n'
                '  let mut total = price\n'
                '  total <- total + 5\n'
                '  total <- total * 2\n'
                '  total\n'
                '\n'
                'print (checkout 10)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_10_mutation_block3',
        "files": {
            'main.pyfun': (
                'let balance start =\n'
                '  let mut acc = start\n'
                '  acc <- acc + 100\n'
                '  acc <- acc - 30\n'
                '  acc <- acc + 50\n'
                '  acc\n'
                '\n'
                'print (balance 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_11_effects_block1',
        "files": {
            'main.pyfun': (
                'let pure total price qty = price * qty\n'
                '\n'
                'let announce price qty =\n'
                '  print (f"total: {total price qty}")\n'
                '\n'
                'announce 12 3\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_11_effects_block2',
        "files": {
            'main.pyfun': (
                'let name = input "Your name: "\n'
                'print (f"Hello, {name}")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_11_effects_block4',
        "files": {
            'main.pyfun': (
                'let pure greet name = f"Hello, {name}"\n'
                '\n'
                'print (greet "ada")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block1',
        "files": {
            'main.pyfun': (
                'extern pure mean: List float -> float = statistics.mean\n'
                '\n'
                'let readings = [2.0, 4.0, 9.0]\n'
                '\n'
                'readings |> mean |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block3',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                '\n'
                'extern flush: unit -> unit = sys.stdout.flush\n'
                '\n'
                'print "written"\n'
                'flush ()\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block4',
        "files": {
            'main.pyfun': (
                'extern type Path\n'
                'extern pure toPath: string -> Path = pathlib.Path\n'
                'extern pure suffix: Path -> string = .suffix\n'
                'extern pure withName: Path -> string -> Path = .with_name\n'
                'extern pure asText: Path -> string = builtins.str\n'
                '\n'
                'let renamed = withName (toPath "report.csv") "summary.csv"\n'
                '\n'
                '"report.csv" |> toPath |> suffix |> print\n'
                'renamed |> asText |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block5',
        "files": {
            'main.pyfun': (
                'type Book = { title: string, pages: int }\n'
                '\n'
                'let bookDecoder =\n'
                '  Decode.map2 (fun title pages -> Book { title = title, pages = pages })\n'
                '    (Decode.field "title" Decode.string)\n'
                '    (Decode.field "pages" Decode.int)\n'
                '\n'
                'let describe r =\n'
                '  match r:\n'
                '    case Ok b: f"{b.title}, {b.pages} pages"\n'
                '    case Error e: f"failed ({e.errorKind})"\n'
                '\n'
                'let wellFormed = """{"title": "Dune", "pages": 412}"""\n'
                'let missingField = """{"title": "Dune"}"""\n'
                '\n'
                'wellFormed |> Decode.decodeString bookDecoder |> describe |> print\n'
                'missingField |> Decode.decodeString bookDecoder |> describe |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block6',
        "files": {
            'main.pyfun': (
                'type Player = Ann | Bob\n'
                'type Msg = Hello Player | Move string | Resign\n'
                'type Turn = { player: Player, msg: Msg, score: Option int }\n'
                '\n'
                'let turn = Turn { player = Bob, msg = Move "K11 a QUIZ", score = Some 42 }\n'
                'let wire = Encode.auto turn\n'
                'print wire\n'
                '\n'
                'let describe t = f"{t.player} played {t.msg}"\n'
                '\n'
                'match Decode.decodeString Decode.auto wire:\n'
                '  case Ok back: print (describe back)\n'
                '  case Error e: print f"failed: {e.errorMessage}"\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block7',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern toThread: (unit -> a) -> Async a = asyncio.to_thread\n'
                '\n'
                'let answer =\n'
                '  async {\n'
                '    let! v = toThread (fun _ -> 6 * 7)\n'
                '    return v\n'
                '  }\n'
                '\n'
                'print (runAsync answer)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_12_python_interop_block9',
        "files": {
            'main.pyfun': (
                'type Book = { title: string, pages: int }\n'
                '\n'
                'let bookDecoder =\n'
                '  Decode.map2 (fun title pages -> Book { title = title, pages = pages })\n'
                '    (Decode.field "title" Decode.string)\n'
                '    (Decode.field "pages" Decode.int)\n'
                '\n'
                'let describe r =\n'
                '  match r:\n'
                '    case Ok b: f"{b.title}, {b.pages} pages"\n'
                '    case Error e: f"failed ({e.errorKind}): {e.errorMessage}"\n'
                '\n'
                'let wellFormed = """{"title": "Dune", "pages": 412}"""\n'
                'let missingField = """{"title": "Dune"}"""\n'
                '\n'
                'wellFormed |> Decode.decodeString bookDecoder |> describe |> print\n'
                'missingField |> Decode.decodeString bookDecoder |> describe |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block1',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  match Option.toResult "bad a" (String.toInt a):\n'
                '    case Error e: Error e\n'
                '    case Ok x:\n'
                '      match Option.toResult "bad b" (String.toInt b):\n'
                '        case Error e2: Error e2\n'
                '        case Ok y: Ok (x + y)\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block2',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  result {\n'
                '    let! x = Option.toResult "bad a" (String.toInt a)\n'
                '    let! y = Option.toResult "bad b" (String.toInt b)\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block3',
        "files": {
            'main.pyfun': (
                'let addStrings a b =\n'
                '  option {\n'
                '    let! x = String.toInt a\n'
                '    let! y = String.toInt b\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addStrings "3" "4")\n'
                'print (addStrings "3" "oops")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block4',
        "files": {
            'main.pyfun': (
                'let double s = String.toInt s |> Option.map (fun n -> n * 2)\n'
                '\n'
                'print (double "21")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block5',
        "files": {
            'main.pyfun': (
                'let counts =\n'
                '  seq {\n'
                '    yield 1\n'
                '    yield 2\n'
                '    yield 3\n'
                '  }\n'
                '\n'
                'counts |> Seq.toList |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block6',
        "files": {
            'main.pyfun': (
                'let squares =\n'
                '  seq {\n'
                '    for x in [1, 2, 3]:\n'
                '      let y = x * x\n'
                '      yield y\n'
                '    yield 100\n'
                '  }\n'
                '\n'
                'squares |> Seq.toList |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_13_computation_expressions_block8',
        "files": {
            'main.pyfun': (
                'let multiply a b =\n'
                '  result {\n'
                '    let! x = Option.toResult "not a number" (String.toInt a)\n'
                '    let! y = Option.toResult "not a number" (String.toInt b)\n'
                '    return x * y\n'
                '  }\n'
                '\n'
                'print (multiply "6" "7")\n'
                'print (multiply "6" "nope")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_14_units_of_measure_block1',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure kg\n'
                '\n'
                'measure N = kg m / s^2                # newton, a derived alias\n'
                '\n'
                'let distance = 100.0<m>\n'
                'let elapsed = 10.0<s>\n'
                'let speed = distance / elapsed        # float<m/s>\n'
                'let side = sqrt 16.0<m^2>             # float<m>\n'
                'let force = 6.0<N>                    # a value in newtons\n'
                '\n'
                'print speed\n'
                'print side\n'
                'print force\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_14_units_of_measure_block3',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'let distance = 240.0<m>\n'
                'let elapsed = 30.0<s>\n'
                '\n'
                '# Speed is distance per unit of time.\n'
                'let speed = distance / elapsed\n'
                '\n'
                'print speed\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_15_modules_block1',
        "files": {
            'main.pyfun': (
                'module Geom =\n'
                '  let square x = x * x\n'
                '  let area w h = w * h\n'
                '  let diagSq w h = square w + square h\n'
                '\n'
                'print (Geom.area 4 5)\n'
                'print (Geom.diagSq 3 4)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_15_modules_block3',
        "files": {
            'main.pyfun': (
                'type Shape =\n'
                '  | Circle float\n'
                '  | Rect float float\n'
                '\n'
                'type Placed = { shape: Shape, x: float, y: float }\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_15_modules_block5',
        "files": {
            'main.pyfun': (
                'let cToF c = c * 9 // 5 + 32\n'
                'let fToC f = (f - 32) * 5 // 9\n'
                '\n'
                'print (cToF 100)\n'
                'print (fToC 212)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_15_modules_block6',
        "files": {
            'main.pyfun': (
                'module Temp =\n'
                '  let cToF c = c * 9 // 5 + 32\n'
                '  let fToC f = (f - 32) * 5 // 9\n'
                '\n'
                'print (Temp.cToF 100)\n'
                'print (Temp.fToC 212)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_16_capstone_block2',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'type Run = { name: string, distance: float, time: float }\n'
                '\n'
                'let runDecoder =\n'
                '  Decode.map3 (fun n d t -> Run { name = n, distance = d, time = t })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "distance" Decode.float)\n'
                '    (Decode.field "time" Decode.float)\n'
                '\n'
                'let input = """[\n'
                '  {"name": "ada", "distance": 100.0, "time": 20.0},\n'
                '  {"name": "bo", "distance": 140.0, "time": 30.0}\n'
                ']"""\n'
                '\n'
                'let report =\n'
                '  match Decode.decodeString (Decode.list runDecoder) input:\n'
                '    case Ok runs:\n'
                '      let names = runs |> List.map (fun r -> r.name) |> String.join ", "\n'
                '      let dist = runs |> List.fold (fun a r -> a + r.distance * 1.0<m>) 0.0<m>\n'
                '      let time = runs |> List.fold (fun a r -> a + r.time * 1.0<s>) 0.0<s>\n'
                '      let avg = dist / time\n'
                '      f"{names}: average speed {avg} m/s over {List.len runs} runs"\n'
                '    case Error e: f"could not read input ({e.errorKind})"\n'
                '\n'
                'print report\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_17_recursion_block1',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                '\n'
                'print (fact 5)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_17_recursion_block2',
        "files": {
            'main.pyfun': (
                'let isEven n = if n == 0 then true else isOdd (n - 1)\n'
                'let isOdd n = if n == 0 then false else isEven (n - 1)\n'
                '\n'
                'print (isEven 10)\n'
                'print (isOdd 7)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_17_recursion_block3',
        "files": {
            'main.pyfun': (
                'let countDown n acc = if n == 0 then acc else countDown (n - 1) (acc + n)\n'
                '\n'
                'print (countDown 100000 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_17_recursion_block4',
        "files": {
            'main.pyfun': (
                'type Expr =\n'
                '  | Num int\n'
                '  | Add Expr Expr\n'
                '  | Mul Expr Expr\n'
                '\n'
                'let eval e =\n'
                '  match e:\n'
                '    case Num n: n\n'
                '    case Add l r: eval l + eval r\n'
                '    case Mul l r: eval l * eval r\n'
                '\n'
                'let tree = Add (Num 1) (Mul (Num 2) (Num 3))\n'
                '\n'
                'print (eval tree)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_17_recursion_block6',
        "files": {
            'main.pyfun': (
                'type Tree =\n'
                '  | Leaf int\n'
                '  | Branch Tree Tree\n'
                '\n'
                'let total t =\n'
                '  match t:\n'
                '    case Leaf n: n\n'
                '    case Branch l r: total l + total r\n'
                '\n'
                'let sample = Branch (Leaf 1) (Branch (Leaf 2) (Leaf 3))\n'
                '\n'
                'print (total sample)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block1',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let fetchScore =\n'
                '  async {\n'
                '    let! x = async { return 20 }\n'
                '    return x + 1\n'
                '  }\n'
                '\n'
                'print (runAsync fetchScore)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block2',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let roll =\n'
                '  async {\n'
                '    print "rolling"\n'
                '    return 6\n'
                '  }\n'
                '\n'
                'let twice =\n'
                '  async {\n'
                '    let! a = roll\n'
                '    let! b = roll\n'
                '    return a + b\n'
                '  }\n'
                '\n'
                'print (runAsync twice)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block3',
        "files": {
            'main.pyfun': 'extern runAsync: Async a -> a = asyncio.run\n',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block5',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern sleep: float -> Async unit = asyncio.sleep\n'
                '\n'
                'let nap =\n'
                '  async {\n'
                '    do! sleep 0.01\n'
                '    return "rested"\n'
                '  }\n'
                '\n'
                'print (runAsync nap)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block6',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let slow n =\n'
                '  async {\n'
                '    do! Async.sleep 0.01\n'
                '    return n\n'
                '  }\n'
                '\n'
                'let main =\n'
                '  async {\n'
                '    let! xs = Async.parallel [slow 1, slow 2, slow 3]\n'
                '    print xs\n'
                '    let! quick = Async.timeout 0.001 (Async.sleep 1.0)\n'
                '    print quick\n'
                '    let! r = Async.catch (slow 4)\n'
                '    match r:\n'
                '      case Ok n: print f"finished with {n}"\n'
                '      case Error e: print f"failed: {e.errorKind}"\n'
                '    return ()\n'
                '  }\n'
                '\n'
                'runAsync main\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block7',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let worker name =\n'
                '  async {\n'
                '    do! Async.sleep 0.01\n'
                '    print f"{name} done"\n'
                '  }\n'
                '\n'
                'let session =\n'
                '  Task.scope (async {\n'
                '    Task.start (worker "a")\n'
                '    Task.start (worker "b")\n'
                '    return "both joined"\n'
                '  })\n'
                '\n'
                'print (runAsync session)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_18_async_block10',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let combined =\n'
                '  async {\n'
                '    let! a = async { return 10 }\n'
                '    let! b = async { return 20 }\n'
                '    return a + b\n'
                '  }\n'
                '\n'
                'print (runAsync combined)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_19_active_patterns_block1',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                '\n'
                'let parity n =\n'
                '  match n:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                '\n'
                'print (parity 4)\n'
                'print (parity 7)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_19_active_patterns_block2',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                '\n'
                'let clamped n =\n'
                '  match n:\n'
                '    case Positive p: p\n'
                '    case _: 0\n'
                '\n'
                'print (clamped 9)\n'
                'print (clamped (0 - 5))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_19_active_patterns_block3',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                '\n'
                'let lineKind s =\n'
                '  match s:\n'
                '    case Blank: "empty"\n'
                '    case _: "text"\n'
                '\n'
                'print (lineKind "   ")\n'
                'print (lineKind "hi")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_19_active_patterns_block5',
        "files": {
            'main.pyfun': (
                'let (|Hot|_|) c = if c >= 25 then Some c else None\n'
                '\n'
                'let describe c =\n'
                '  match c:\n'
                '    case Hot t: f"hot at {t}"\n'
                '    case _: "not hot"\n'
                '\n'
                'print (describe 30)\n'
                'print (describe 5)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_20_build_your_own_ce_block1',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: f x\n'
                '      case None: None\n'
                '  let return_ x = Some x\n'
                '\n'
                'let addOpt a b =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    return x + y\n'
                '  }\n'
                '\n'
                'print (addOpt (Some 3) (Some 4))\n'
                'print (addOpt (Some 3) None)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_20_build_your_own_ce_block3',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: f x\n'
                '      case None: None\n'
                '  let return_ x = Some x\n'
                '\n'
                'let addThree a b c =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    let! z = c\n'
                '    return x + y + z\n'
                '  }\n'
                '\n'
                'print (addThree (Some 1) (Some 2) (Some 3))\n'
                'print (addThree (Some 1) None (Some 3))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_21_strings_and_numbers_block1',
        "files": {
            'main.pyfun': (
                'let title = String.concat "Hello, " "World"\n'
                'let loud = String.upper title\n'
                'let words = String.split ", " title\n'
                'let csv = String.join "," words\n'
                'let first5 = String.slice 0 5 title\n'
                '\n'
                'print title\n'
                'print loud\n'
                'print words\n'
                'print csv\n'
                'print first5\n'
                'print (Option.withDefault 0 (String.toInt "41"))\n'
                'print (Option.withDefault 0 (String.toInt "x"))\n'
                'print (Option.withDefault 0.0 (String.toFloat "2.5"))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_21_strings_and_numbers_block2',
        "files": {
            'main.pyfun': (
                'print (Format.fixed 2 3.14159)\n'
                'print (Format.thousands 2 1234567.891)\n'
                'print (Format.grouped 1234567)\n'
                'print (Format.percent 1 0.256)\n'
                'print (Format.padLeft 8 " " "42")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_21_strings_and_numbers_block3',
        "files": {
            'main.pyfun': (
                'let who = "Ada"\n'
                'let score = 41\n'
                '\n'
                'let line = f"{who} scored {score} ({String.upper who})"\n'
                'let debug = f"{score=}"\n'
                'let braces = f"{{literal braces}} around {score}"\n'
                'let winPath = r"C:\\Users\\pyfun\\data.csv"\n'
                'let banner = """== pyfun ==\n'
                'a "quoted" word"""\n'
                'let emoji = "hi \\u{1F600}"\n'
                '\n'
                'print line\n'
                'print debug\n'
                'print braces\n'
                'print winPath\n'
                'print banner\n'
                'print (String.len "café")\n'
                'print (String.len emoji)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_21_strings_and_numbers_block4',
        "files": {
            'main.pyfun': (
                'let million = 1_000_000\n'
                'let mask = 0xFF\n'
                'let bits = 0b1010\n'
                'let perm = 0o17\n'
                'let lightSpeed = 3.0e8\n'
                'let tower = 2.0 ** 3.0 ** 2.0\n'
                'let q = 17 // 5\n'
                'let r = 17 % 5\n'
                'let inRange = 0 <= 7 < 10\n'
                '\n'
                'print million\n'
                'print mask\n'
                'print bits\n'
                'print perm\n'
                'print lightSpeed\n'
                'print tower\n'
                'print q\n'
                'print r\n'
                'print inRange\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_21_strings_and_numbers_block6',
        "files": {
            'main.pyfun': (
                'let label raw =\n'
                '  let n = Option.withDefault 0 (String.toInt raw)\n'
                '  f"{raw} parses to {n}"\n'
                '\n'
                'print (label "42")\n'
                'print (label "oops")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_22_opaque_types_block1',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'opaque type Email = string\n'
                '\n'
                'let uid = UserId "u-1001"\n'
                'let contact = Email "ana@example.org"\n'
                '\n'
                'let describe u =\n'
                '  match u:\n'
                '    case UserId s: s\n'
                '\n'
                'uid |> describe |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_22_opaque_types_block3',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                '\n'
                'extern pure shout: UserId -> string = str.upper\n'
                '\n'
                'let uid = UserId "u-1001"\n'
                'let loud = uid |> shout\n'
                'print loud\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_22_opaque_types_block5',
        "files": {
            'main.pyfun': (
                'opaque type OrderId = string\n'
                '\n'
                'let orderLabel o =\n'
                '  match o:\n'
                '    case OrderId s: String.concat "order " s\n'
                '\n'
                '# The id arrives as a plain string from the outside world.\n'
                'let raw = "o-9"\n'
                '\n'
                'let label = orderLabel (OrderId raw)\n'
                '\n'
                'print label\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_23_keyword_arguments_block1',
        "files": {
            'main.pyfun': (
                'extern parseHex: string -> int = int(base = 16)\n'
                '\n'
                'let raw = "ff"\n'
                '\n'
                'raw |> parseHex |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_23_keyword_arguments_block2',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let fromHex s = parseIn s 16\n'
                'let fromBinary s = parseIn s 2\n'
                '\n'
                'let a = "ff"\n'
                'let b = "1011"\n'
                '\n'
                'a |> fromHex |> print\n'
                'b |> fromBinary |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_23_keyword_arguments_block3',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let ff = parseIn "ff"\n'
                '\n'
                'ff 16 |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_23_keyword_arguments_block4',
        "files": {
            'main.pyfun': (
                '# Two externs that differ only in the base each one pins.\n'
                'extern parseHex: string -> int = int(base = 16)\n'
                'extern parseBinary: string -> int = int(base = 2)\n'
                '\n'
                'let hex = "ff"\n'
                'let binary = "1011"\n'
                '\n'
                'hex |> parseHex |> print\n'
                'binary |> parseBinary |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__learn_23_keyword_arguments_block5',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                '\n'
                'let fromHex s = parseIn s 16\n'
                'let fromBinary s = parseIn s 2\n'
                '\n'
                'let hex = "ff"\n'
                'let binary = "1011"\n'
                '\n'
                'hex |> fromHex |> print\n'
                'binary |> fromBinary |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block2',
        "files": {
            'main.pyfun': (
                'let grade score =\n'
                '  match score:\n'
                '    case s if s >= 90: "A"\n'
                '    case s if s >= 80: "B"\n'
                '    case _: "C"\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block3',
        "files": {
            'main.pyfun': (
                'extern pure mean:  List float -> float = statistics.mean\n'
                'extern pure stdev: List float -> float = statistics.stdev\n'
                '\n'
                'type Summary = { n: int, mean: float, stdev: float }\n'
                '\n'
                'let summarize xs =\n'
                '  Summary { n = List.len xs, mean = mean xs, stdev = stdev xs }\n'
                '\n'
                'let report xs =\n'
                '  let s = summarize xs\n'
                '  f"n={s.n} mean={s.mean} sd={s.stdev}"\n'
                '\n'
                'print (report [1.0, 2.0, 3.0, 4.0])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block4',
        "files": {
            'main.pyfun': (
                "extern parseInt: string -> int = int          # Python's built-in int()\n"
                '\n'
                'let safe s = Result.withDefault 0 (try (parseInt s))\n'
                'print (safe "42")     # 42\n'
                'print (safe "oops")   # 0   (the ValueError was caught into an Error)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block5',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '# forget a case and the compiler reports the missing witness, e.g. `Rect _ _ is not matched`\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block6',
        "files": {
            'main.pyfun': (
                'type User = { name: string, age: int }\n'
                '\n'
                'let user =\n'
                '  Decode.map2 (fun name age -> User { name = name, age = age })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "age" Decode.int)\n'
                '\n'
                '# Decode.decodeString user : string -> Result User Exception\n'
                '#   good input   -> Ok (a typed User)\n'
                '#   missing/bad  -> Error (a value describing exactly what was wrong)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block7',
        "files": {
            'main.pyfun': (
                'let describe =\n'
                '  List.filter (fun x -> x > 0)\n'
                '  >> List.map ((*) 2)\n'
                '  >> List.fold (+) 0\n'
                '\n'
                'let total = [1, -2, 3] |> describe    # (1 + 3) * 2 = 8\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block8',
        "files": {
            'main.pyfun': (
                'let pure add a b = a + b        # OK: no effects\n'
                '# let pure shout n = print n    # compile error: `print` performs `io`\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block9',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure kg\n'
                'measure N = kg m / s^2          # derived aliases expand to base units\n'
                '\n'
                'let speed = 100<m> / 10<s>      # float<m/s>\n'
                'let force = 10<N>\n'
                '# let bad = 100<m> + 10<s>      # compile error: m vs s\n'
                'let side = sqrt 16.0<m^2>       # float<m>, unit-aware roots\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block10',
        "files": {
            'main.pyfun': (
                'let checked ok v =\n'
                '  result {                      # railway-oriented; short-circuits on Error\n'
                '    let! x = if ok then Ok v else Error "bad"\n'
                '    return x + 1\n'
                '  }\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block11',
        "files": {
            'main.pyfun': (
                'let planck = 6.626e-34\n'
                'let million = 1_000_000\n'
                'let mask = 0xFF\n'
                'let who = "Ada"\n'
                'let line = f"{who} scored {million} ({String.upper who})"\n'
                'let path = r"C:\\Users\\pyfun"    # raw string, backslashes literal\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__readme_block12',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'print (area (Circle 2.0))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__rationale_block1',
        "files": {
            'main.pyfun': (
                'let add a b = a + b          # int -> int -> int\n'
                'let greet n = print n        # string ->{io} unit\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__internals_06_units_block1',
        "files": {
            'main.pyfun': (
                'measure m\n'
                '\n'
                'let side = sqrt 16.0<m^2>\n'
                '\n'
                'print side\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__internals_readme_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'measure m\n'
                '\n'
                'let shapes = [Circle 2.0, Rect 3.0 4.0]\n'
                'let total = shapes |> List.fold (fun acc s -> acc + area s) 0.0\n'
                'let side = sqrt 16.0<m^2>\n'
                'print (f"total {total}, side {side}")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__introduction_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
                '    case Rect w h: w * h\n'
                '\n'
                'let shapes = [Circle 2.0, Rect 3.0 4.0]\n'
                'shapes |> List.fold (fun acc s -> acc + area s) 0.0 |> print\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

DOC_CHECK_CASES = [
    {
        'id': 'check__learn_01_values_and_inference_block2',
        "files": {
            'main.pyfun': (
                'let apples = 4\n'
                'let oranges = 3\n'
                'let fruit = apples + ?count\n'
                'print (f"total fruit: {fruit}")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_02_functions_currying_pipes_block2',
        "files": {
            'main.pyfun': (
                'let double x = x + x\n'
                'let triple x = x + x + x\n'
                '\n'
                'let result = 3 |> double |> ?stage\n'
                'print result\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_03_option_block2',
        "files": {
            'main.pyfun': (
                'let label s =\n'
                '  match String.toInt s:\n'
                '    case Some n: f"number: {n}"\n'
                '\n'
                'print (label "7")\n'
                'print (label "nope")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_04_result_block2',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                '\n'
                'let describe s =\n'
                '  match parseInt s:\n'
                '    case Ok n: f"ok: {n}"\n'
                '    case Error e: f"bad: {e.errorKind}"\n'
                '\n'
                'print (describe "88")\n'
                'print (describe "bad")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_05_adts_and_match_block3',
        "files": {
            'main.pyfun': (
                'let describeSign n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case m if m > 0: "positive"\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_05_adts_and_match_block5',
        "files": {
            'main.pyfun': (
                'type Light =\n'
                '  | Red\n'
                '  | Amber\n'
                '  | Green\n'
                '\n'
                'let action l =\n'
                '  match l:\n'
                '    case Red: "stop"\n'
                '    case Green: "go"\n'
                '\n'
                'print (action Red)\n'
                'print (action Amber)\n'
                'print (action Green)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_06_records_block3',
        "files": {
            'main.pyfun': (
                'type Account = { name: string, balance: int }\n'
                '\n'
                'let opened = Account { name = "Ada", balance = 0 }\n'
                'let funded = { opened with balance = ? }\n'
                '\n'
                'print funded.name\n'
                'print funded.balance\n'
                'print opened.balance\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_07_collections_block3',
        "files": {
            'main.pyfun': (
                'let ns = [4, 8, 15, 16, 23]\n'
                '\n'
                'let total = List.fold ? 0 ns\n'
                'let atTen = Option.withDefault ? (List.get 10 ns)\n'
                '\n'
                'print total\n'
                'print atTen\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_08_tuples_block4',
        "files": {
            'main.pyfun': 'let (Some x) = Some 1\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_08_tuples_block6',
        "files": {
            'main.pyfun': (
                'let names = ["ada", "alan"]\n'
                'let scores = [10, 9]\n'
                '\n'
                'let line pair =\n'
                '  match pair:\n'
                '    case (name, score): ?\n'
                '\n'
                'let lines = List.zip names scores |> List.map line\n'
                '\n'
                'lines |> String.join ", " |> print\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_09_typed_holes_block1',
        "files": {
            'main.pyfun': (
                'let names = ["ada", "grace", "alan"]\n'
                '\n'
                'let headline names =\n'
                '  names\n'
                '  |> List.map ?upper\n'
                '  |> String.join ", "\n'
                '\n'
                'names |> headline |> print\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_09_typed_holes_block2',
        "files": {
            'main.pyfun': (
                'let scores = Map.add "ada" 10 (Map.add "alan" 9 Map.empty)\n'
                '\n'
                'let report name =\n'
                '  Map.tryFind name scores\n'
                '  |> Option.withDefault ?missing\n'
                '  |> ?render\n'
                '\n'
                'print (report "ada")\n'
                'print (report "cy")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_10_mutation_block2',
        "files": {
            'main.pyfun': (
                'let balance start =\n'
                '  let acc = start\n'
                '  acc <- acc + 100\n'
                '  acc <- acc - 30\n'
                '  acc <- acc + 50\n'
                '  acc\n'
                '\n'
                'print (balance 0)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_11_effects_block3',
        "files": {
            'main.pyfun': (
                'let pure greet name =\n'
                '  print (f"Hello, {name}")\n'
                '  name\n'
                '\n'
                'let greeting = greet "ada"\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_12_python_interop_block2',
        "files": {
            'main.pyfun': 'extern flush: unit -> unit = sys.stdout.flush\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_12_python_interop_block8',
        "files": {
            'main.pyfun': (
                'type Book = { title: string, pages: int }\n'
                '\n'
                'let bookDecoder =\n'
                '  Decode.map2 (fun title pages -> Book { title = title, pages = pages })\n'
                '    (Decode.field "title" ?titleDec)\n'
                '    (Decode.field "pages" ?pagesDec)\n'
                '\n'
                'let describe r =\n'
                '  match r:\n'
                '    case Ok b: f"{b.title}, {b.pages} pages"\n'
                '    case Error e: f"failed ({e.errorKind}): {e.errorMessage}"\n'
                '\n'
                'let wellFormed = """{"title": "Dune", "pages": 412}"""\n'
                'let missingField = """{"title": "Dune"}"""\n'
                '\n'
                'wellFormed |> Decode.decodeString bookDecoder |> describe |> print\n'
                'missingField |> Decode.decodeString bookDecoder |> describe |> print\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_13_computation_expressions_block7',
        "files": {
            'main.pyfun': (
                'let multiply a b =\n'
                '  result {\n'
                '    let! x = ?\n'
                '    let! y = ?\n'
                '    return x * y\n'
                '  }\n'
                '\n'
                'print (multiply "6" "7")\n'
                'print (multiply "6" "nope")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_14_units_of_measure_block2',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'let distance = 240.0<m>\n'
                'let elapsed = 30.0<s>\n'
                '\n'
                '# Speed is distance per unit of time. This line does not type-check yet.\n'
                'let speed = distance + elapsed\n'
                '\n'
                'print speed\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_15_modules_block2',
        "files": {
            'main.pyfun': (
                'import Geometry\n'
                'import Store\n'
                '\n'
                'let floor = Geometry.area 4 5\n'
                'let nine = Geometry.square 3\n'
                'let widen = Geometry.area 10\n'
                'let strip = widen 2\n'
                '\n'
                'let hit = Store.lookup 1 |> Option.withDefault 0\n'
                'let miss = Store.lookup 9 |> Option.withDefault 0\n'
                '\n'
                'print floor\n'
                'print nine\n'
                'print strip\n'
                'print hit\n'
                'print miss\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_15_modules_block4',
        "files": {
            'main.pyfun': (
                'import Shapes\n'
                '\n'
                'type Scene = { name: string, item: Shapes.Placed }\n'
                '\n'
                'let scene =\n'
                '  Scene { name = "demo", item = Shapes.Placed { shape = Shapes.Circle 2.0, x = 0.0, y = 0.0 } }\n'
                '\n'
                'let describe p =\n'
                '  match p.shape:\n'
                '    case Shapes.Circle r: f"circle of radius {r}"\n'
                '    case Shapes.Rect w h: f"{w} by {h} rectangle"\n'
                '\n'
                'print scene.name\n'
                'print (describe scene.item)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_16_capstone_block1',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                '\n'
                'type Run = { name: string, distance: float, time: float }\n'
                '\n'
                'let runDecoder =\n'
                '  Decode.map3 (fun n d t -> Run { name = n, distance = d, time = t })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "distance" ?)\n'
                '    (Decode.field "time" Decode.float)\n'
                '\n'
                'let input = """[\n'
                '  {"name": "ada", "distance": 100.0, "time": 20.0},\n'
                '  {"name": "bo", "distance": 140.0, "time": 30.0}\n'
                ']"""\n'
                '\n'
                'let report =\n'
                '  match Decode.decodeString (Decode.list runDecoder) input:\n'
                '    case Ok runs:\n'
                '      let names = runs |> List.map (fun r -> r.name) |> String.join ", "\n'
                '      let dist = runs |> List.fold (fun a r -> a + r.distance * ?) 0.0<m>\n'
                '      let time = runs |> List.fold (fun a r -> a + r.time * 1.0<s>) 0.0<s>\n'
                '      let avg = dist / ?\n'
                '      f"{names}: average speed {avg} m/s over {List.len runs} runs"\n'
                '    case Error e: f"could not read input ({e.errorKind})"\n'
                '\n'
                'print report\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_17_recursion_block5',
        "files": {
            'main.pyfun': (
                'type Tree =\n'
                '  | Leaf int\n'
                '  | Branch Tree Tree\n'
                '\n'
                'let total t =\n'
                '  match t:\n'
                '    case Leaf n: n\n'
                '    case Branch l r: ?\n'
                '\n'
                'let sample = Branch (Leaf 1) (Branch (Leaf 2) (Leaf 3))\n'
                '\n'
                'print (total sample)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_18_async_block4',
        "files": {
            'main.pyfun': 'let pure grab x = async { return x + 1 }\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_18_async_block8',
        "files": {
            'main.pyfun': 'let stray = Task.start (Async.sleep 1.0)\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_18_async_block9',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                '\n'
                'let combined =\n'
                '  async {\n'
                '    let! a = async { return 10 }\n'
                '    let! b = async { return ? }\n'
                '    return a + b\n'
                '  }\n'
                '\n'
                'print (runAsync combined)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_19_active_patterns_block4',
        "files": {
            'main.pyfun': (
                'let (|Hot|_|) c = if ? then Some c else None\n'
                '\n'
                'let describe c =\n'
                '  match c:\n'
                '    case Hot t: f"hot at {t}"\n'
                '    case _: "not hot"\n'
                '\n'
                'print (describe 30)\n'
                'print (describe 5)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_20_build_your_own_ce_block2',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: ?\n'
                '      case None: None\n'
                '  let return_ x = ?\n'
                '\n'
                'let addThree a b c =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    let! z = c\n'
                '    return x + y + z\n'
                '  }\n'
                '\n'
                'print (addThree (Some 1) (Some 2) (Some 3))\n'
                'print (addThree (Some 1) None (Some 3))\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_21_strings_and_numbers_block5',
        "files": {
            'main.pyfun': (
                'let label raw =\n'
                '  let n = Option.withDefault ? (String.toInt raw)\n'
                '  f"{raw} parses to {n}"\n'
                '\n'
                'print (label "42")\n'
                'print (label "oops")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_22_opaque_types_block2',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'opaque type Email = string\n'
                '\n'
                'let describe u =\n'
                '  match u:\n'
                '    case UserId s: s\n'
                '\n'
                'let bad = describe (Email "ana@example.org")\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__learn_22_opaque_types_block4',
        "files": {
            'main.pyfun': (
                'opaque type OrderId = string\n'
                '\n'
                'let orderLabel o =\n'
                '  match o:\n'
                '    case OrderId s: String.concat "order " s\n'
                '\n'
                '# The id arrives as a plain string from the outside world.\n'
                'let raw = "o-9"\n'
                '\n'
                '# This line does not type-check yet: orderLabel wants an OrderId.\n'
                'let label = orderLabel raw\n'
                '\n'
                'print label\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__readme_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                '# `area` handles Circle but forgets Rect, so Pyfun refuses to compile it:\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__rationale_block2',
        "files": {
            'main.pyfun': 'extern get : string ->{async} bytes = httpx.get\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__internals_05_exhaustiveness_block1',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                '\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.14159 * r * r\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
]


@pytest.mark.parametrize("case", DOC_RUN_CASES, ids=[c["id"] for c in DOC_RUN_CASES])
def test_documented_program_prints_exact_output(run, workdir, case):
    """CATCHES: a compiler whose output for a documented, runnable example computes or
    prints something other than what the reference prints (and the lesson promises)."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", DOC_COMPILE_CASES, ids=[c["id"] for c in DOC_COMPILE_CASES])
def test_documented_program_compiles_to_exact_python(run, workdir, case):
    """CATCHES: different readable Python for a documented example: the lowering shown to
    students (match/case, dataclasses, closures, helpers) must stay byte-identical."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", DOC_CHECK_CASES, ids=[c["id"] for c in DOC_CHECK_CASES])
def test_documented_broken_example_reports_exact_diagnostics(run, workdir, case):
    """CATCHES: an exercise starter that the reimplementation accepts, or reports with a
    different message, location, caret span, hole note or summary line."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
