"""`pyfun compile` over a corpus of Pyfun programs harvested from the project's own test-suite and docs.

Each case writes one program to `prog.pyfun` and runs `pyfun compile prog.pyfun` in the default mode,
with `--native` (isinstance ladders + annotations for mypyc) or with `--target 3.11` (no PEP 701
f-strings), comparing the exact emitted Python, the `note:` lines and exit code with the reference.
"""

import json

import pytest

from conftest import golden

ARGS = {
    "compile": ["compile", "prog.pyfun"],
    "native": ["compile", "prog.pyfun", "--native"],
    "py311": ["compile", "prog.pyfun", "--target", "3.11"],
}

# case id -> (mode, program source)
CASES = {
    "native_000_c759bb04": ("native", '# A taste of the type-checked Phase 3 subset that compiles to runnable Python.\n#   pyfun check   examples/hello.pyfun     (type-check)\n#   pyfun compile examples/hello.pyfun     (emit Python)\n#   pyfun run     examples/hello.pyfun     (run it)\n\n# Algebraic data types: a plain enum. (`Option a = None | Some a` is built in.)\ntype Color = Red | Green | Blue\n\n# Records: named-field product types (nominal; field names are unique).\ntype Point = { x: int, y: int }\n\n# Curried function: inferred type int -> int -> int. `pure` is an opt-in\n# assertion that the function performs no effects (no `io`); the compiler infers\n# effects everywhere and only checks them where you ask. Effects are erased at\n# lowering. (`let pure shout n = print n` would be a compile error.)\nlet pure add a b = a + b\n\n# Partial application (functools.partial); full application (add(1, 4)).\nlet inc = add 1\nlet five = 4 |> inc\n\n# Recursion is implicit: a function is in scope in its own body, like Python\'s\n# `def` (no `rec` keyword). Deep recursion shares Python\'s stack limit; use the\n# `List`/`Seq` combinators for stack-safe bulk work.\nlet fact n =\n  if n == 0 then 1\n  else n * fact (n - 1)\n\n# Standard combinators are built in (`DESIGN.md` §6): `id : \'a -> \'a`,\n# `const : \'a -> \'b -> \'a`, `ignore : \'a -> unit`, `flip` swaps a function\'s\n# first two arguments. `flip` is effect-polymorphic; the rest are pure. (A user\n# `let id x = x` would shadow the builtin, like any other prelude name.)\nlet same = id 42                       # 42\nlet always7 = const 7 "discarded"      # 7\nlet subtract a b = a - b\nlet backwards = flip subtract 3 10     # subtract 10 3 = 7\nlet zeroed = List.map (const 0) [1, 2, 3]   # [0, 0, 0]\nlet dropped = ignore 42                # unit (None) — ignore discards its argument\n\n# Doc comments: a `##` line at column 0 attaches to the following top-level\n# declaration as documentation (LSP hover shows it below the type), unlike an\n# ordinary `#` comment. It erases at compile time.\n## Returns 1 when the flag is set, else 0.\nlet pick b = if b then 1 else 0\n\n# Multi-line doc comment: consecutive `##` lines join into one doc block (with\n# `\\n` between them), attached to the declaration that follows — here a `type`.\n# This sum also shows the offside layout — one `| Variant` per line in an indented\n# block after `=` (the F#/ML habit); `Color` above uses the inline `A | B | C`\n# form. Both parse identically (a leading `|` is optional; the printer\n# canonicalizes back to one line).\n## A traffic signal.\n## `Walk` when clear, `Wait` while it counts down, `Stop` otherwise. Ordered by\n## declaration, so `Walk < Wait < Stop` under the derived comparison.\ntype Signal =\n  | Walk\n  | Wait\n  | Stop\n\n# Typed holes (shown as a comment — a hole blocks compilation by design, so this\n# file can still `run`): write `?` or `?name` in expression position and the\n# compiler reports the type it expects there — plus in-scope bindings that fit\n# directly (`try:`) and functions whose result fits, applied to more holes\n# (`or:`) — for type-driven development. E.g.\n#     let use = String.concat ?g "!"\n# makes `pyfun check` report `note: hole ?g has type string — try: greeting — or:\n# String.upper ?, String.fromInt ?` and hover show it; `compile`/`run` refuse\n# until it\'s filled. Fill inward from the types (and the suggested fits).\n\n# Blocks: an indented body is a sequence of statements ending in the value. They\n# open after `=` (a `let` body), `->` (a lambda), `case P:` (a `match` arm), `then`/`else`.\n# `let mut` + `<-` give local mutation; reassigning a plain `let` is a compile\n# error (immutable by default). Lowers to a flat Python statement sequence.\nlet scaled a b =\n  let mut acc = a\n  acc <- acc + b\n  acc <- acc * 2\n  acc\n\n# A closure that reassigns a captured `mut` — `tally` mutates `running` across\n# calls. The compiler emits Python\'s `nonlocal`/`global` so the capture is correct\n# (F# auto-boxes a captured mutable into a reference cell; same idea).\nlet accumulate =\n  let mut running = 0\n  let tally x =\n    running <- running + x\n    running\n  let first = tally 10\n  tally 5                             # 15  (10 then +5)\n\n# A block in a `match` arm (opened after `case P:`).\nlet describeSign n =\n  match n:\n    case 0: "zero"\n    case _:\n        let positive = n > 0\n        if positive then "positive" else "negative"\n\n# Exhaustive pattern matching over an ADT (checked at compile time).\nlet unwrap o =\n  match o:\n    case Some v: v\n    case None: 0\n\nlet answer = unwrap (Some 42)\n\n# An as-pattern (`p as x`) binds the whole matched value alongside destructuring —\n# and it\'s transparent to the exhaustiveness check (`Some v as w` covers Some).\nlet doubleIfSome o =\n  match o:\n    case Some v as w: w\n    case None: None\nlet stillFortyTwo = doubleIfSome (Some 42)   # Some 42\n\nlet rank c =\n  match c:\n    case Red: 1\n    case Green: 2\n    case Blue: 3\n\n# Mutual recursion works implicitly (no `rec`/`and`): `isEven` sees `isOdd` and\n# vice versa, defined in either order.\nlet isEven n = if n == 0 then true else isOdd (n - 1)\nlet isOdd n = if n == 0 then false else isEven (n - 1)\nlet tenEven = isEven 10               # true\n\n# Or-patterns: `case a | b:` matches any alternative (Python-identical). All\n# alternatives must bind the same variables (here, none).\nlet size n =\n  match n:\n    case 1 | 2 | 3: "small"\n    case _: "big"\n\n# Guards: a `case` arm may carry an `if` condition. A guarded arm is refutable —\n# it never counts toward exhaustiveness, so a catch-all `case _` is still needed.\nlet sign n =\n  match n:\n    case 0: "zero"\n    case m if m > 0: "positive"\n    case _: "negative"\n\n# `elif` — sugar for `else if`; `if`/`then`/`else` stay (an inline expression, not\n# `:`-framed). The printer canonicalizes any else-if chain to `elif`.\nlet grade n =\n  if n >= 90 then "A"\n  elif n >= 80 then "B"\n  elif n >= 70 then "C"\n  else "F"\n\n# Higher-order composition: (\'b -> \'c) -> (\'a -> \'b) -> \'a -> \'c.\nlet compose = fun f g x -> f (g x)\nlet inc2 = compose inc inc\nlet seven = inc2 five\n\n# Function composition operators: `>>` is left-to-right (f then g), `<<` is\n# right-to-left (math ∘). Tighter than `|>`, so `x |> f >> g` = `x |> (f >> g)`.\nlet twice x = x * 2\nlet incThenDouble = inc >> twice\nlet doubleThenInc = inc << twice\nlet eight = incThenDouble 3            # twice (inc 3) = 8\nlet sevenC = doubleThenInc 3           # inc (twice 3) = 7\n# Backward pipe `<|` applies a function to an argument (F#\'s `<|`), dropping parens\n# on the right: `inc <| twice 3` = `inc (twice 3)`. Right-associative.\nlet sevenB = inc <| twice 3            # inc (twice 3) = 7\n\n# In-file modules: a namespace of `let` bindings. Members see each other\n# unqualified inside (`area` calls `square`); outside they are `Geom.member`.\nmodule Geom =\n  let square x = x * x\n  let area w h = w * h\n  let diagSq w h = square w + square h\nlet floorArea = Geom.area 4 5         # 20\nlet diag = Geom.diagSq 3 4            # 25\n\n# Computation expressions (F# showcase features):\n#   result {} — railway-oriented, short-circuits on Error (built-in Ok/Error).\nlet checked ok v =\n  result {\n    let! x = if ok then Ok v else Error 0\n    return x + 1\n  }\n\n#   option {} — the same railway over Option, for chaining lookups that may find\n#   nothing. One `case None` arm covers the whole chain instead of one per step.\nlet firstTwo xs =\n  option {\n    let! a = List.get 0 xs\n    let! b = List.get 1 xs\n    return a + b\n  }\nprint (firstTwo [10, 20, 30])      # Some(30)\nprint (firstTwo [10])              # None_ — the emitted class name, `None` being taken in Python\n\n#   seq {} — a lazy sequence, lowered to a Python generator.\nlet small =\n  seq {\n    yield 1\n    yield 2\n    yield 3\n  }\n\n#   async {} — lowered to a Python coroutine (async def / await). A coroutine must be\n#   awaited somewhere, so run one to a value with an `extern` over `asyncio.run`.\nextern runAsync: Async a -> a = asyncio.run\nlet computed =\n  async {\n    let! x = async { return 20 }\n    return x + 1\n  }\nprint (runAsync computed)          # 21\n\n# User-defined CE builders: any in-file `module` providing `bind`/`return_` (and\n# `yield_`/`combine`/`delay`/… for sequence builders) is a builder. `Maybe { … }`\n# desugars to `Maybe.bind`/`Maybe.return_` calls — ordinary inference does the rest.\nmodule Maybe =\n  let bind m f =\n    match m:\n      case Some x: f x\n      case None: None\n  let return_ x = Some x\nlet addOpt a b =\n  Maybe {\n    let! x = a\n    let! y = b\n    return x + y\n  }\n\n# Tuples: structural (anonymous) products, `(a, b, c)`. `()` is unit and `(x)` is\n# grouping, so a tuple has two or more elements. They lower ~1:1 to Python tuples\n# and destructure in `match` (a single variable pattern is exhaustive).\nlet pairUp a b = (a, b)\nlet origin = (0, 0)\nlet swap p =\n  match p:\n    case (a, b): (b, a)\nlet labelled = (1, "one", true)              # (int, string, bool)\nlet firstOf t =\n  match t:\n    case (a, _, _): a\n\n# Units of measure: dimensional analysis at compile time, erased at runtime.\nmeasure m\nmeasure s\nmeasure kg\n\n# Derived-measure aliases name a compound of base units (and may build on each\n# other). They expand to base units, so `<N>` and `<kg m / s^2>` are the same type.\nmeasure N = kg m / s^2               # newton\nmeasure Pa = N / m^2                 # pascal, built on N\n\nlet push = 10<N>\nlet panel = 2<m^2>\nlet stress = push / panel            # float<Pa>, dimensionally N/m^2\n\nlet distance = 100<m>\nlet elapsed = 10<s>\nlet speed = distance / elapsed       # true division -> float<m/s>\nlet trip = distance // 4<m>          # floor division -> int (dimensionless)\nlet leftover = distance % 30<m>      # modulo -> int<m> (unit-preserving); 100 % 30 = 10\n\n# `area` is unit-polymorphic: int<\'u> -> int<\'v> -> int<\'u \'v>.\nlet area w h = w * h\nlet floor = area 4<m> 5<m>            # int<m^2>\n# `distance + elapsed` would be a compile error: int<m> vs int<s>.\n\n# Unit-aware roots: sqrt : float<\'u^2> -> float<\'u> (√area = length) and\n# cbrt : float<\'u^3> -> float<\'u> (∛volume = length). The unit\'s exponents halve\n# (sqrt) or divide by 3 (cbrt); a non-square/non-cube unit is a compile error\n# (`sqrt 2.0<m>`, `cbrt 2.0<m^2>` are rejected dimensionally). These two are the\n# only tractable unit-carrying power ops — `**` stays dimensionless.\nlet side = sqrt 16.0<m^2>            # float<m> — 4.0, unit halved (m^2 -> m)\nlet edge = cbrt 64.0<m^3>            # float<m> — 4.0, unit thirded (m^3 -> m)\n\n# Float literals support scientific notation (`1e6`, `2.5e-3`) — the exponent sign\n# is part of the literal. Physics constants read naturally, units and all:\nlet lightSpeed = 3.0e8<m/s>          # float<m/s>\nlet planck = 6.626e-34               # float\n\n# Prefix negation `-e`: numeric and unit-preserving. It\'s a prefix operator (not a\n# negative-literal token), so `-` is subtraction with a left operand and negation\n# without — `depth - 2` subtracts, `-depth` negates.\nlet depth = -20<m>                    # int<m>, a negative literal\nlet rebound = -(3 + 4)               # -7 (a looser operand is parenthesized)\n\n# Numeric conversions round/floor/ceil/truncate : float<\'u> -> int<\'u>, unit-\n# preserving like abs/min/max (round is a Python builtin; the rest use `math`).\nlet rounded = round 3.7              # 4\n# (`floor` is shadowed below by a user binding of the same name — user\n# definitions shadow prelude names — so this uses `truncate`.)\nlet truncated = truncate speed       # 10   (float<m/s> -> int<m/s>, unit kept)\n# String.toFloat is a total parse (Option float), mirroring String.toInt.\nlet parsedF = Option.withDefault 0.0 (String.toFloat "2.71828")  # 2.71828\n\n# Exponentiation `**` is float-only, right-associative, and binds tighter than\n# unary minus (so `-2.0 ** 2.0` is `-(2.0 ** 2.0)`, like Python).\nlet cube = 3.0 ** 3.0                # 27.0\nlet tower = 2.0 ** 3.0 ** 2.0        # 512.0  (right-assoc: 2 ^ (3 ^ 2))\nlet negPow = -2.0 ** 2.0            # -4.0   (`**` tighter than unary minus)\n\n# Numeric-literal ergonomics: `_` digit separators and 0x/0o/0b bases.\nlet million = 1_000_000             # 1000000\nlet mask = 0xFF                     # 255  (hex; also 0o17 octal, 0b1010 binary)\n\n# Externs: typed imports of arbitrary Python callables (`DESIGN.md` §6). The\n# Pyfun name equals the Python name unless a `= target` clause gives a dotted\n# path (which is imported automatically). Type variables are bare lowercase, as\n# in `type` decls. The boundary is effectful-by-default — a plain `extern` is\n# `io` at full application — unless asserted `pure`; `math.fabs` is pure.\n# (`extern sqrt`/`extern cbrt` would clash — sqrt/cbrt are the built-in unit-aware\n# roots now, so a Python name that isn\'t a Pyfun builtin is used here.)\nextern show: a -> string = str\nextern pure fabs: float -> float = math.fabs\n\n# Declared-arrow effect annotations: effects are inferred everywhere, but an\n# `extern` (or declared `type`) arrow may state effect labels explicitly with\n# `->{label, …}` — beyond the default inferred `io`, e.g. the `async` label.\n# An async Python client returns a coroutine, so its result is the `Async`\n# type and `let!` inside an `async { }` block is where it is awaited; an\n# `->{async}` arrow that returns anything else is rejected. (Uncalled here, so\n# it erases; calling `sleepAsync` would make its caller perform `async`, so it\n# couldn\'t sit inside a `let pure`.)\nextern sleepAsync: float ->{async} Async unit = asyncio.sleep\n\nlet label = show 42                  # "42"  (str(42))\nlet root = fabs (0.0 - 3.0)          # 3.0   (math.fabs(-3.0))\n\n# `try e` catches a Python exception (e.g. from an `extern`) into a `Result a\n# Exception`, so the imperative FFI boundary becomes the FP error type. The\n# reserved `Exception` record exposes `errorKind` (the class name) and\n# `errorMessage`. `try` binds looser than `+` but tighter than `|>`.\nextern parseInt: string -> int = int\nlet parsed42 = Result.withDefault 0 (try (parseInt "42"))    # 42\nlet parsedBad = Result.withDefault 0 (try (parseInt "oops")) # 0  (ValueError caught)\nlet errorKindOf s =\n  match try (parseInt s):\n    case Ok n: "ok"\n    case Error e: e.errorKind                                # string literal patterns\n\n# Lists: the eager `List a` collection (lowers to a Python list). Literals are\n# comma-separated `[a, b, c]`. Collection functions are module-qualified\n# (`List.map`, `Set.add`, `Map.tryFind`) — the module disambiguates a shared name\n# like `len`, so no overloading is needed. The higher-order list ops are\n# effect-polymorphic (mapping an impure function makes the call impure).\nlet ns = [1, 2, 3, 4, 5]\nlet squares = List.map (fun x -> x * x) ns   # [1, 4, 9, 16, 25]\nlet bigs = List.filter (fun x -> x > 2) ns   # [3, 4, 5]\nlet total = List.fold (fun a b -> a + b) 0 ns # 15\nlet count = List.len ns                      # 5\n\n# An operator section `(op)` is a binary operator as a curried function, so the\n# fold above shortens to `(+)`; `(*) 2` partially applies it (F#-style).\nlet product = List.fold (*) 1 ns             # 120\nlet doubled = List.map ((*) 2) ns            # [2, 4, 6, 8, 10]\n\n# Completeness ops, each with big-O honest to a Python list (an array): `get` is\n# O(1) and total (returns `Option`, so no IndexError — no `xs[0]` syntax exists);\n# `contains` is O(n) (use `Set` for O(1)); `concat` O(n+m); `sort` O(n log n);\n# `find` O(n) first-match. There\'s no cheap prepend — that\'s the linked-list non-goal.\nlet third = Option.withDefault 0 (List.get 2 ns)   # 3 (0-based)\nlet missing = Option.withDefault 0 (List.get 9 ns) # 0 (out of bounds -> None)\nlet hasThree = List.contains 3 ns            # true\nlet joined = List.concat ns [6, 7]           # [1, 2, 3, 4, 5, 6, 7]\nlet ordered = List.sort [3, 1, 2]            # [1, 2, 3]\n# Derived ordering: user sum types / records / tuples compare structurally, so\n# `<` (and `List.sort`) work on them. A sum orders by variant declaration order\n# then field-by-field (Red < Green < Blue).\nlet sortedColors = List.sort [Blue, Red, Green]  # [Red, Green, Blue]\nlet redFirst = Red < Green                       # true\n# Built-in Option/Result order too: None < Some, Ok < Error (payloads orderable).\nlet sortedOpts = List.sort [Some 3, None, Some 1]  # [None, Some 1, Some 3]\nlet firstBig = List.find (fun x -> x > 3) ns # Some 4\n\n# Sets and maps lower to Python `set` / `dict`; `Map.tryFind` returns the built-in\n# `Option`, consumed with the `Option` module.\nlet uniq = Set.ofList [1, 1, 2, 3]           # {1, 2, 3}\nlet scores = Map.add "ada" 10 (Map.add "alan" 9 Map.empty)\nlet ada = Option.withDefault 0 (Map.tryFind "ada" scores)   # 10\nlet nobody = Option.withDefault 0 (Map.tryFind "x" scores)  # 0\n\n# The `Option` module chains lookups: `bind` sequences Option-returning steps,\n# `filter` keeps a value only if it passes, `toResult` bridges to `Result`.\nlet doubled = Option.bind (fun n -> Some (n * 2)) (Map.tryFind "ada" scores)  # Some 20\nlet bigScore = Option.filter (fun n -> n > 9) (Map.tryFind "alan" scores)     # None (9 <= 9)\nlet adaOrErr = Option.toResult "no ada" (Map.tryFind "ada" scores)           # Ok 10\n\n# `List.zip` pairs two lists into a list of tuples; `Map.ofList` builds a map from\n# that pair list (and `Map.toList` is its inverse) — both ride on tuples.\nlet names = ["ada", "alan"]\nlet ages = [36, 41]\nlet byName = Map.ofList (List.zip names ages)\nlet adaAge = Option.withDefault 0 (Map.tryFind "ada" byName)  # 36\nlet entries = Map.toList byName               # [("ada", 36), ("alan", 41)]\n\n# Strings: the `String` module over the built-in `string` type. All pure; there is\n# no `char` type, so `String.toList` yields single-character strings. `String.toInt`\n# is a total parse — it returns the built-in `Option`, `None` on failure.\nlet title = String.concat "Hello, " "World"   # "Hello, World"\nlet loud = String.upper title                 # "HELLO, WORLD"\nlet words = String.split ", " title           # ["Hello", "World"]\nlet csv = String.join "," words               # "Hello,World"\n# `slice` is total Python slicing (clamps out of range); `tryIndexOf` returns an\n# Option (None when absent), so neither can raise.\nlet sub = String.slice 0 5 title              # "Hello"\nlet commaAt = Option.withDefault (0 - 1) (String.tryIndexOf "," title)  # 5\nlet parsed = Option.withDefault 0 (String.toInt "41")   # 41\nlet unparsed = Option.withDefault 0 (String.toInt "x")  # 0\n# Non-ASCII string literals are real UTF-8 (not one Latin-1 byte per char), so\n# `String.len "café"` is 4, not 5 — and the emitted Python is correctly encoded.\nlet cafeLen = String.len "café"                # 4 (é is one character)\n# Escapes: \\" \\\\ \\n \\t \\r and Rust-style \\u{HEX} (decoded to the character).\nlet emojiLen = String.len "hi \\u{1F600}"       # 4 ("hi " + 😀)\n# Raw strings `r"..."` — no escape processing, backslashes are literal (handy for\n# Windows paths and regex). `r"a\\nb"` is 4 chars (a, \\, n, b), not a newline.\nlet winPath = r"C:\\Users\\pyfun"                # C:\\Users\\pyfun (literal backslashes)\nlet rawLen = String.len r"a\\nb"                # 4 (backslash and n are literal)\n\n# String interpolation: `f"...{expr}..."` (Python-style). Holes take any full\n# expression and are stringified; `{{`/`}}` are literal braces. Lowers 1:1 to a\n# Python f-string (targets Python 3.12+).\nlet who = "Ada"\nlet scoreLine = f"{who} scored {parsed} ({String.upper who})"   # "Ada scored 41 (ADA)"\nlet sumLine = f"{parsed} doubled is {parsed + parsed}"          # "41 doubled is 82"\n# Self-documenting `{expr=}` holes echo the source before the value (Python\'s rule):\nlet debugLine = f"{parsed=}"                                    # "parsed=41"\n# Triple-quoted strings span lines (newlines and lone quotes are literal content;\n# escapes still process): plain `"""..."""`, interpolated `f"""..."""` (holes as\n# usual), and raw `r"""..."""` (backslashes literal too).\nlet banner = """== pyfun ==\na "quoted" word"""\nlet summary = f"""who: {who}\nscore: {parsed}"""\n# Raw triple-quoted `r"""..."""`: spans lines AND leaves backslashes literal.\nlet rawBlock = r"""C:\\logs\na\\tb"""                                # backslashes + newline all literal\n\n# Prelude builtins (`print`, `abs`/`min`/`max`) make results observable:\n#   pyfun run examples/hello.pyfun\n# Consecutive `print` statements are separated by Pyfun\'s offside rule (a line\n# break back to the left margin), not braces or semicolons. Units erase, so the\n# printed numbers are plain Python numbers.\nprint answer                         # 42\nprint dropped                        # None  (ignore : \'a -> unit)\nprint stillFortyTwo                   # Some(42)  (as-pattern binds the whole value)\nprint tenEven                          # True  (mutual recursion: isEven/isOdd)\nprint (fact 5)                       # 120  (recursive)\nprint seven                          # 7\nprint eight                          # 8   (inc >> twice)\nprint sevenC                         # 7   (inc << twice)\nprint sevenB                         # 7   (inc <| twice 3, backward pipe)\nprint (rank Green)                   # 2\nprint floor                          # 20\nprint speed                          # 10.0  (true division)\nprint trip                           # 25    (floor division)\nprint leftover                       # 10    (modulo, unit-preserving)\nprint lightSpeed                     # 300000000.0  (scientific notation, unit erased)\nprint planck                         # 6.626e-34    (scientific notation)\nprint rounded                        # 4     (round, float -> int)\nprint truncated                      # 10    (truncate, unit-preserving)\nprint side                           # 4.0   (unit-aware sqrt: float<m^2> -> float<m>)\nprint edge                           # 4.0   (unit-aware cbrt: float<m^3> -> float<m>)\nprint parsedF                        # 2.71828  (String.toFloat)\nprint cube                            # 27.0  (exponentiation)\nprint tower                           # 512.0  (right-associative `**`)\nprint negPow                          # -4.0  (`**` binds tighter than unary minus)\nprint million                         # 1000000  (digit separators)\nprint mask                            # 255      (0xFF)\nprint stress                         # 5.0   (derived-measure alias, erased)\nprint (max distance 50<m>)           # 100\nprint depth                          # -20                   (negative literal)\nprint rebound                        # -7                    (`-(3 + 4)`)\n\n# Comparison (`comparison \'a => …`) and equality (`\'a -> \'a -> bool`, structural\n# for ADTs) both yield bool. `<` is comparison here because of the space; `5<m>`\n# without a space is a unit annotation.\nprint (answer == 42)                 # True\nprint (seven < 10)                   # True\nprint (speed < 50<m/s>)              # True   (dimensional comparison)\nprint (Some 42 == Some answer)       # True   (structural ADT equality)\n# Chained comparison (Python-style): `lo <= x < hi` means `lo <= x and x < hi`,\n# evaluating `x` once. Lowers to Python\'s own chained comparison.\nprint (0 <= seven < 10)              # True   (chained comparison)\n\n# Logical operators: `and` / `or` / `not` (Python keywords, Python precedence).\nprint (seven < 10 and answer == 42)  # True\nprint (not (seven == 8) or false)    # True\n\n# Records: construct with `{ f = v }`, access with `.f`, copy-and-update with\n# `{ r with f = v }`. The record type is resolved from the field names.\nlet here = Point { x = 3, y = 4 }\nlet shifted = { here with x = 10 }\nlet dot r = r.x + r.y                 # field access fixes `r : Point`\nprint here.x                          # 3\nprint shifted.x                       # 10\nprint (dot here)                      # 7\nprint here                            # Point(3, 4)\n\n# Nested-update sugar: a dotted path `{ r with a.b = v }` updates a field deep in\n# a record — sugar for `{ r with a = { r.a with b = v } }`. Arbitrary depth, and\n# the base is evaluated once with sibling fields (here `start.y`, `finish`) copied.\ntype Segment = { start: Point, finish: Point }\nlet seg = Segment { start = Point { x = 0, y = 0 }, finish = here }\nlet moved = { seg with start.x = 99 }\nprint moved.start.x                   # 99  (updated through the path)\nprint moved.start.y                   # 0   (sibling preserved)\nprint moved.finish.x                  # 3   (untouched field preserved)\nprint (scaled 3 4)                    # 14   ((3 + 4) * 2, via local mutation)\nprint accumulate                      # 15   (closure capturing a mutable)\n\n# Record patterns: destructure in `match`. `{ x }` shorthand binds the field; a\n# pattern may name a subset of fields, and `{ x, y }` is an exhaustive catch-all.\nlet describe p =\n  match p:\n    case Point { x = 0, y = 0 }: "origin"\n    case Point { x = 0 }: "y-axis"\n    case Point { x, y }: "elsewhere"\nprint (describe (Point { x = 0, y = 0 }))   # origin\nprint (describe here)                 # elsewhere\n\n# List/sequence patterns in `match` over a `List`: `[]`, a fixed `[x]`, and a\n# `*rest` star that may sit ANYWHERE (Python\'s one-star rule) — `[x, *rest]`\n# (head + tail), `[*init, last]` (all but the last), `[a, *mid, z]` (first and\n# last, middle bound). `[]` plus a star arm is exhaustive.\nlet shape xs =\n  match xs:\n    case []: "empty"\n    case [only]: "one"\n    case [a, *mid, z]: "first and last, some middle"\nlet lastOf xs =\n  match xs:\n    case []: 0\n    case [*init, last]: last\nprint (shape [1, 2, 3, 4])            # first and last, some middle\nprint (shape [7])                     # one\nprint (lastOf [10, 20, 30])           # 30  (non-last star: [*init, last])\n\n# Externs in action (call out to Python\'s str / math.fabs).\nprint label                           # 42\nprint root                            # 3.0\n\n# `try` in action: recover a default, and read the caught exception\'s kind.\nprint parsed42                        # 42\nprint parsedBad                       # 0    (try caught the ValueError)\nprint (errorKindOf "nope")            # ValueError\n\n# Lists in action.\nprint squares                         # [1, 4, 9, 16, 25]\nprint bigs                            # [3, 4, 5]\nprint total                           # 15\nprint count                           # 5\nprint product                         # 120                  (`(*)` section)\nprint doubled                         # [2, 4, 6, 8, 10]     (`(*) 2` section)\nprint third                           # 3    (List.get, O(1), total via Option)\nprint hasThree                        # True (List.contains, O(n))\nprint joined                          # [1, 2, 3, 4, 5, 6, 7]  (List.concat)\nprint ordered                         # [1, 2, 3]  (List.sort, O(n log n))\nprint sortedColors                    # [Red, Green, Blue]  (derived ADT ordering)\nprint sortedOpts                      # [None_, Some(1), Some(3)]  (Option orders)\nprint redFirst                        # True\nprint firstBig                        # Some(4)  (List.find, first match)\n\n# Sets, maps, and options in action.\nprint (Set.len uniq)                  # 3\nprint ada                             # 10\nprint nobody                          # 0\nprint doubled                         # Some(20)  (Option.bind)\nprint bigScore                        # None_     (Option.filter, 9 <= 9)\nprint adaOrErr                        # Ok(10)    (Option.toResult)\nprint adaAge                          # 36   (zip -> Map.ofList -> tryFind)\nprint entries                         # [(\'ada\', 36), (\'alan\', 41)]\n\n# Strings in action.\nprint loud                            # HELLO, WORLD\nprint words                           # [\'Hello\', \'World\']\nprint csv                             # Hello,World\nprint sub                             # Hello  (String.slice, total)\nprint commaAt                         # 5      (String.tryIndexOf -> Option int)\nprint (String.len title)             # 12\nprint parsed                          # 41   (total parse of "41")\nprint unparsed                        # 0    (String.toInt "x" -> None)\nprint cafeLen                         # 4    (UTF-8 "café" is 4 characters)\nprint emojiLen                        # 4    (\\u{1F600} is one character)\nprint winPath                         # C:\\Users\\pyfun   (raw string)\nprint rawLen                          # 4    (r"a\\nb" is 4 literal characters)\nprint scoreLine                       # Ada scored 41 (ADA)   (f-string)\nprint sumLine                         # 41 doubled is 82\nprint debugLine                       # parsed=41             (f-string `{x=}`)\nprint banner                          # two lines: == pyfun == / a "quoted" word\nprint summary                         # two lines: who: Ada / score: 41\nprint (String.len rawBlock)           # 12   (r""" — backslashes/tab-escape are literal chars)\n\n# In-file module members.\nprint floorArea                       # 20\nprint diag                            # 25\n\n# A block-bodied `match` arm.\nprint (describeSign 0)                # zero\nprint (describeSign 7)                # positive\nprint (describeSign (0 - 3))          # negative\n\n# Or-patterns, guards, and `elif`.\nprint (size 2)                        # small  (or-pattern 1 | 2 | 3)\nprint (size 9)                        # big\nprint (sign 5)                        # positive  (guard: m if m > 0)\nprint (sign (0 - 4))                  # negative\nprint (grade 95)                      # A  (elif chain)\nprint (grade 83)                      # B\nprint (grade 68)                      # F\n\n# A user-defined computation expression (the Maybe monad).\nprint (addOpt (Some 3) (Some 4))      # Some(7)\nprint (addOpt (Some 3) None)          # None_  (short-circuits)\n\n# Tuples: construction, destructuring, and the Python tuple they become.\nprint (pairUp 1 2)                     # (1, 2)\nprint origin                          # (0, 0)\nprint (swap (1, 2))                   # (2, 1)\nprint (firstOf labelled)              # 1\n\n# Active patterns (DESIGN.md 7.2.1): named recognizers whose cases are matched\n# like constructors. A total pattern (|A|B|) is a closed case set, so its match\n# needs no `_`; a partial pattern (|A|_|) returns Option (the case binds the\n# payload) or bool (a pure predicate, binds nothing) and needs a fallthrough.\nlet (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\nlet parity n =\n  match n:\n    case Even: "even"\n    case Odd: "odd"\n\nlet (|Positive|_|) n = if n > 0 then Some n else None\nlet clamped n =\n  match n:\n    case Positive p: p\n    case _: 0\n\nlet (|Blank|_|) s = String.strip s == ""\nlet lineKind s =\n  match s:\n    case Blank: "empty"\n    case _: "text"\n\nprint (parity 4)                      # even\nprint (parity 7)                      # odd\nprint (clamped 9)                     # 9\nprint (clamped (0 - 5))               # 0\nprint (lineKind "   ")                # empty\nprint (lineKind "hi")                 # text\n'),
    "py311_001_1ef87e56": ("py311", '# Direct trains from a station, grouped by destination — a Network Rail SCHEDULE\n# feed turned into a readable Markdown timetable, with NO Python helper: the file\n# is streamed, parsed, and rendered entirely in Pyfun.\n#\n#   cargo run -- run examples/interop/network-rail/chippenham.pyfun\n#\n# This is the boundary-vs-engine interop pattern taken to its limit — even the\n# streaming boundary is Pyfun. The file object from `open`/`gzip.open` is consumed\n# as a lazy `Seq string`, so a ~3 GB NDJSON snapshot streams in constant memory; a\n# substring prefilter skips JSON parsing on the lines that can\'t match; and the\n# `Decode` module turns each surviving line into typed data — no dict-poking, no\n# bespoke Python. `open`/`gzip.open`\'s mode + encoding and `write_text`\'s encoding\n# + newline are pinned as `extern` keyword arguments (see the externs below), so the Python\n# call carries `encoding="utf-8"` without any positional filler.\n#\n# Runs out of the box against the bundled `sample.ndjson`. For the real feed\n# (register at https://opendata.nationalrail.co.uk / Network Rail data feeds),\n# point `dataFile` at your snapshot — the EXACT filename, `.json` or `.json.gz`\n# (a `.gz` is detected by extension and streamed without decompressing).\n#\n# Performance: driving the ~20M-line loop through `Seq.fold` is correctness- and\n# clarity-first, not throughput-first — expect a minute or two on the full feed\n# (a native Python loop is faster, but that puts the hot path back in Python).\n#\n# STP caveat: counts reflect the day-of-week pattern of permanent + new schedules\n# minus full cancellations (stp "C"), deduped by (departure, destination). A\n# specific calendar date may differ. A full snapshot is all `Create` records, so\n# transaction type isn\'t checked.\n\n# `mode="rt"` opens the file as text and `encoding="utf-8"` reads UTF-8 instead of\n# the platform locale (cp1252 on Windows) — both correct for the feed and ~5s\n# faster on the full file. Pinning them as `extern` keyword arguments reaches\n# `encoding` (a keyword-only / deep-positional arg) with no positional filler.\nextern openText : string -> Seq string = builtins.open(mode="rt", encoding="utf-8")\nextern gzipText : string -> Seq string = gzip.open(mode="rt", encoding="utf-8")\nextern type Path\nextern toPath : string -> Path = pathlib.Path\nextern writeText : Path -> string -> int = pathlib.Path.write_text(encoding="utf-8", newline="\\n")\n\ntype Stop = { tiploc: string, arr: string, dep: string }\ntype Run  = { uid: string, days: string, stp: string, stops: List Stop }\ntype Leg  = { dest: string, finalDest: string, rdays: string, depMin: int, arrMin: int, jt: int, via: List string }\n\nlet dataFile = "examples/interop/network-rail/sample.ndjson"\nlet outFile  = "examples/interop/network-rail/chippenham-routes.md"\n\n# --- streaming boundary, in Pyfun: the file object is a lazy Seq of lines ---\nlet lines path =\n  if String.endsWith ".gz" path then gzipText path else openText path\n\n# --- decode the relevant lines into typed data (parse, don\'t validate) ---\nlet optStr key = Decode.oneOf [Decode.field key Decode.string, Decode.succeed ""]\n\nlet tipDec =\n  Decode.field "TiplocV1"\n    (Decode.map2 (fun c n -> (c, n))\n      (Decode.field "tiploc_code" Decode.string)\n      (optStr "tps_description"))\n\nlet stopDec =\n  Decode.map3 (fun t a d -> (t, a, d))\n    (Decode.field "tiploc_code" Decode.string)\n    (optStr "public_arrival")\n    (optStr "public_departure")\n\nlet schedDec =\n  Decode.field "JsonScheduleV1"\n    (Decode.map4 (fun uid days stp stops -> (uid, days, stp, stops))\n      (Decode.field "CIF_train_uid" Decode.string)\n      (optStr "schedule_days_runs")\n      (optStr "CIF_stp_indicator")\n      (Decode.field "schedule_segment" (Decode.field "schedule_location" (Decode.list stopDec))))\n\n# Fold the lazy line Seq into (tiploc names, Chippenham-calling runs). A cheap\n# substring test skips JSON parsing on the millions of lines that can\'t match —\n# the same prefilter the Python did, now in Pyfun and in constant memory.\nlet ingest acc line =\n  match acc:\n    case (names, runs):\n      if String.contains "TiplocV1" line then\n        match Decode.decodeString tipDec line:\n          case Ok (c, n): (Map.add c n names, runs)\n          case Error _: acc\n      else if String.contains "JsonScheduleV1" line and String.contains "CHIPNHM" line then\n        match Decode.decodeString schedDec line:\n          case Ok r: (names, List.concat runs [r])\n          case Error _: acc\n      else acc\n\nlet scan path = Seq.fold ingest (Map.empty, []) (lines path)\n\n# --- shape the decoded tuples into typed records ---\nlet toStop t =\n  match t:\n    case (tp, a, d): Stop { tiploc = tp, arr = a, dep = d }\n\nlet toRun r =\n  match r:\n    case (uid, days, stp, stops):\n      Run { uid = uid, days = days, stp = stp, stops = List.map toStop stops }\n\n# A stop is a public calling point iff it advertises a public time.\nlet calls s = (s.arr != "" and s.arr != "0000") or (s.dep != "" and s.dep != "0000")\n\nlet toMin hhmm =\n  match (String.toInt (String.slice 0 2 hhmm), String.toInt (String.slice 2 4 hhmm)):\n    case (Some h, Some m): h * 60 + m\n    case _: -1\n\nlet fmt2 n = if n < 10 then f"0{n}" else f"{n}"\nlet showTime m = f"{fmt2 (m // 60)}:{fmt2 (m % 60)}"\n\nlet jtime dep arr =\n  let d = arr - dep\n  if d < 0 then d + 1440 else d\n\nlet fromChippenham stops =\n  match stops:\n    case []: None\n    case [s, *rest]:\n      if s.tiploc == "CHIPNHM" and calls s then Some (s.dep, rest)\n      else fromChippenham rest\n\nlet lastTiploc stops =\n  match stops:\n    case []: ""\n    case [s]: s.tiploc\n    case [_, *rest]: lastTiploc rest\n\nlet walkLegs days term depM via stops =\n  match stops:\n    case []: []\n    case [s, *rest]:\n      if calls s then\n        let arrM = toMin s.arr\n        let onward = List.concat via [s.tiploc]\n        if arrM < 0 then walkLegs days term depM onward rest\n        else\n          let leg = Leg { dest = s.tiploc, finalDest = term, rdays = days, depMin = depM,\n                          arrMin = arrM, jt = jtime depM arrM, via = via }\n          List.concat [leg] (walkLegs days term depM onward rest)\n      else walkLegs days term depM via rest\n\nlet legsOfRun r =\n  if r.stp == "C" then []\n  else\n    match fromChippenham r.stops:\n      case None: []\n      case Some (chippDep, downstream):\n        let depM = toMin chippDep\n        if depM < 0 then []\n        else walkLegs r.days (lastTiploc downstream) depM [] downstream\n\nlet runsOn day days = String.slice day (day + 1) days == "1"\n\nlet dedupLegs legs =\n  let step acc leg =\n    match acc:\n      case (seen, out):\n        let k = f"{leg.depMin}|{leg.dest}"\n        match Map.tryFind k seen:\n          case Some _: (seen, out)\n          case None: (Map.add k true seen, List.concat out [leg])\n  match List.fold step (Map.empty, []) legs:\n    case (_, out): out\n\nlet groupByDest acc leg =\n  Map.add leg.dest (List.concat (Option.withDefault [] (Map.tryFind leg.dest acc)) [leg]) acc\n\nlet insertByDep leg sorted =\n  match sorted:\n    case []: [leg]\n    case [x, *rest]:\n      if leg.depMin <= x.depMin then List.concat [leg] sorted\n      else List.concat [x] (insertByDep leg rest)\n\nlet sortLegs legs = List.fold (fun acc l -> insertByDep l acc) [] legs\n\nlet minOf xs =\n  match xs:\n    case []: 0\n    case [x]: x\n    case [x, *rest]:\n      let m = minOf rest\n      if x < m then x else m\n\nlet maxOf xs =\n  match xs:\n    case []: 0\n    case [x]: x\n    case [x, *rest]:\n      let m = maxOf rest\n      if x > m then x else m\n\n# --- title-casing (feed descriptions are UPPERCASE) ---\n# Uppercase the first *alphabetic* char in a char list, leave the rest. The test\n# `String.upper c != c` is true only for a lowercase letter, so "(south"\n# capitalizes the s, not the "(".\nlet capFirst chars =\n  match chars:\n    case []: []\n    case [c, *rest]:\n      if String.upper c != c then List.concat [String.upper c] rest\n      else List.concat [c] (capFirst rest)\n\nlet capWord w = String.join "" (capFirst (String.toList w))\nlet titleHyphen w = String.join "-" (List.map capWord (String.split "-" w))\nlet titleCase name = String.join " " (List.map titleHyphen (String.split " " (String.lower name)))\n\n# --- rendering (Markdown) ---\nlet nameOf names tp = titleCase (Option.withDefault tp (Map.tryFind tp names))\nlet plural n word = if n == 1 then f"{n} {word}" else f"{n} {word}s"\nlet rangeStr lo hi = if lo == hi then f"{lo} min" else f"{lo}-{hi} min"\n\nlet renderService names leg =\n  let stopStr =\n    match leg.via:\n      case []: "direct"\n      case _:\n        let viaStr = String.join ", " (List.map (nameOf names) leg.via)\n        f"via {viaStr}"\n  let onward = if leg.dest == leg.finalDest then "" else f" _(to {nameOf names leg.finalDest})_"\n  f"- **{showTime leg.depMin} → {showTime leg.arrMin}** · {leg.jt} min · {stopStr}{onward}"\n\nlet renderGroup names g =\n  match g:\n    case (dest, legs):\n      let times = List.map (fun l -> l.jt) legs\n      let tr = plural (List.len legs) "train"\n      let header = f"### {nameOf names dest} — {tr}, {rangeStr (minOf times) (maxOf times)}"\n      let body = String.join "\\n" (List.map (renderService names) (sortLegs legs))\n      f"{header}\\n\\n{body}"\n\nlet daySection names label day allLegs =\n  let legs = dedupLegs (List.filter (fun l -> runsOn day l.rdays) allLegs)\n  let pairs = List.map (fun g -> match g: case (dest, ls): (nameOf names dest, renderGroup names g))\n                       (Map.toList (List.fold groupByDest Map.empty legs))\n  let body = String.join "\\n\\n" (List.map (fun p -> match p: case (nm, txt): txt) (List.sort pairs))\n  f"## {label}\\n\\n{body}"\n\nlet buildReport names raw =\n  let allLegs = List.fold (fun acc r -> List.concat acc (legsOfRun r)) [] (List.map toRun raw)\n  let intro = "# Direct services from Chippenham\\n\\n_Every station reachable directly (no change) from Chippenham, grouped by destination, in departure order. Counts reflect the weekly day-of-week pattern of permanent + new schedules minus cancellations; a specific date may differ._"\n  let wd = daySection names "Monday–Friday (representative day: Tuesday)" 1 allLegs\n  let sa = daySection names "Saturday" 5 allLegs\n  let su = daySection names "Sunday" 6 allLegs\n  String.join "\\n\\n" [intro, wd, sa, su]\n\nlet _ =\n  match scan dataFile:\n    case (names, raw): writeText (toPath outFile) (buildReport names raw)\n\nprint (f"Wrote Markdown direct Chippenham services to {outFile}")\n'),
    "py311_002_b60a4fd3": ("py311", '''opaque type UserId = string
type Row = { class: string, id: UserId, ok: Result int string }
let row = Row { class = "a", id = UserId "u1", ok = Error "no" }
let wire = Encode.auto row
print wire
match Decode.decodeString Decode.auto wire:
  case Ok r: print (r == row)
  case Error e: print e.errorMessage'''),
    "py311_003_3d30bb8c": ("py311", '''# asyncio — structured concurrency with `Task.scope`/`Task.start`, and a mailbox
# agent over `asyncio.Queue`, the F# `MailboxProcessor` shape.
#
#   pyfun run examples/interop/structured_concurrency.pyfun
#
# Runs offline. Every task is owned by a scope: `Task.scope` opens an
# `asyncio.TaskGroup` around an async body and does not return until every task
# started with `Task.start` has finished (or cancels them all if one fails).
# `Task.start` performs the `spawn` effect, and a `Task.scope` body is the only
# place that effect is discharged, so there is no way to start a task nothing
# will join, and no `cancel` to forget.

extern import asyncio
extern runAsync: Async a -> a = asyncio.run

# The mailbox: an asyncio queue as an opaque handle. `put_nowait` posts from
# anywhere; `get` is a coroutine, so its result is the `Async` type and `let!`
# is where the agent waits for the next message.
extern type Queue
extern newQueue: unit -> Queue = asyncio.Queue
extern post: Queue -> a -> unit = .put_nowait
extern take: Queue -> Async a = .get()

# The protocol is one ADT: spectators, reconnection or a clock are new
# constructors, not new plumbing.
type Msg = Said string | Tick | Quit

# One step of the agent's state: an effect and the next count. Sync, so the
# recursive call below stays a *direct* tail call.
let heard count s =
  print f"agent heard {s}"
  count + 1

let finished count = async { return count }

# The agent: one loop that is a `match` over the message, the loop's state
# threaded through the recursion. The self tail call compiles to a `while True:`
# inside the one coroutine (`DESIGN.md` §5.4), so an agent that handles a
# message a second for a year is still on its first stack frame.
let agentLoop inbox count =
  async {
    let! msg = take inbox
    return! (match msg:
      case Said s: agentLoop inbox (heard count s)
      case Tick: agentLoop inbox count
      case Quit: finished count)
  }

# A producer posts from its own task. The block ends in a plain call, which is
# `return ()` for a fire-and-forget block.
let producer inbox =
  async {
    for s in ["hello", "world"]:
      do! Async.sleep 0.01
      post inbox (Said s)
    post inbox Tick
    post inbox Quit
  }

# The session: the producer runs as a task of the scope while the agent awaits
# in the body; the closing of the scope joins the producer. Nothing here can
# leak past the end of `session`.
let session =
  Task.scope (async {
    let inbox = newQueue ()
    Task.start (producer inbox)
    let! count = agentLoop inbox 0
    return count
  })

let count = runAsync session
print f"agent handled {count} messages"

# `Task.start` performs `spawn`, and only a `Task.scope` body discharges it, so a
# start outside a scope is a compile error ("this starts a task outside any
# `Task.scope`"), not a leaked task at run time.
'''),
    "native_004_5248f597": ("native", '''
        let xs = [1, 2, 3, 1, 2]
        let taken = List.takeWhile (fun x -> x < 3) xs
        let dropped = List.dropWhile (fun x -> x < 3) xs
        let desc = List.sortByDescending (fun x -> x) xs
        let counted = List.countBy (fun x -> x % 2) xs
        let uniqBy = Seq.toList (Seq.distinctBy (fun x -> x % 2) (Seq.ofList xs))
        let copies = Seq.toList (Seq.replicate 3 "a")
        let none = Seq.toList Seq.empty
        let at = Seq.get 2 (Seq.ofList xs)
        let final = Seq.last (Seq.ofList xs)
        let doubled = Seq.sumBy (fun x -> x * 2) (Seq.ofList xs)
        let biggest = Seq.max (Seq.ofList xs)
        let smallest = Seq.min (Seq.ofList xs)
        let joined = Seq.reduce (fun a b -> a + b) (Seq.ofList xs)
        let holds = Option.forall (fun x -> x > 0) (Some 1)
        let has = Option.contains 1 (Some 1)
        let okHas = Result.contains 1 (Ok 1)
        let negative = sign (-5)
        let zero = sign 0
        let positive = sign 42
        '''),
    "compile_005_b1875d33": ("compile", '''
        let xs = [3, 1, 4, 1, 5]
        let biggest = List.max xs
        let smallest = List.min xs
        let noMax = List.max (List.drop 9 [1])
        let doubled = List.sumBy (fun x -> x * 2) [1, 2, 3]
        let mean = List.average [1.0, 2.0, 4.0]
        let joined = List.reduce (fun a b -> a + b) [1, 2, 3]
        let split = List.partition (fun x -> x > 2) xs
        let apart = List.unzip (List.zip [1, 2] ["a", "b"])
        let flat = List.flatten [[1, 2], [3]]
        let squares = List.init 4 (fun i -> i * i)
        let copies = List.replicate 3 "x"
        let updated = List.updateAt 1 99 [1, 2, 3]
        let untouched = List.updateAt 9 99 [1, 2, 3]
        let inserted = List.insertAt 1 99 [1, 2, 3]
        let removed = List.removeAt 1 [1, 2, 3]
        let pairs = List.pairwise [1, 2, 3]
        let windows = List.windowed 2 [1, 2, 3]
        let chunks = List.chunkBySize 2 [1, 2, 3]
        '''),
    "py311_006_39a54025": ("py311", '''# Decode (built-in) — JSON into your own typed records, totally. THE showcase.
#
#   pyfun run examples/interop/json_to_adt.pyfun
#
# The lesson every language teaches on JSON is "parse, don't validate": turn untrusted,
# dynamically-typed input into your *own* typed data at the edge, so the rest of the
# program can't be fed a wrong shape. Pyfun ships an Elm-style `Decode` module — a
# `Decoder a` is a pure, total recipe, and `Decode.decodeString` runs it over a JSON
# string to yield `Result a Exception`. Bad input is a value you handle, never a crash.

type User = { name: string, age: int, roles: List string }

# A decoder is built compositionally: `Decode.field` pulls one object field and runs
# a decoder on it; `Decode.map3` combines three field decoders into one that builds
# the record. No hand-written field access, no per-field error handling — the module
# threads the `Result` railway for you. `Decode.string`/`int` are strict: a JSON
# number where a string is expected is an `Error`, not a silent coercion.
let userDecoder =
  Decode.map3 (fun name age roles -> User { name = name, age = age, roles = roles })
    (Decode.field "name" Decode.string)
    (Decode.field "age" Decode.int)
    (Decode.field "roles" (Decode.list Decode.string))

# Consuming the result is an exhaustive `match` — the compiler makes you handle both
# outcomes. `Exception` exposes `errorKind` (the Python class name) and `errorMessage`.
let describe r =
  match r:
    case Ok u: f"""{u.name} ({u.age}): {String.join ", " u.roles}"""
    case Error e: f"decode failed ({e.errorKind}): {e.errorMessage}"

# A well-formed object decodes to a typed `User`, array field and all.
print (describe (Decode.decodeString userDecoder """{"name": "ada", "age": 36, "roles": ["admin", "dev"]}"""))
# A missing field short-circuits — no crash, a value describing the failure.
print (describe (Decode.decodeString userDecoder """{"name": "bob", "age": 40}"""))
# A wrong type is caught the same way (age is a string, not a number).
print (describe (Decode.decodeString userDecoder """{"name": "cy", "age": "old", "roles": []}"""))
# So is malformed JSON.
print (describe (Decode.decodeString userDecoder """not json at all"""))

# Output:
#   ada (36): admin, dev
#   decode failed (KeyError): 'roles'
#   decode failed (ValueError): expected an int, got str
#   decode failed (JSONDecodeError): Expecting value: line 1 column 1 (char 0)
#
# The whole pipeline is PURE (no `io`) — a `let pure` over `Decode.decodeString` type-
# checks, because the curated module knows JSON parsing has no side effects (the raw
# `extern json.loads` boundary in json_decode.pyfun is conservatively `io`). More
# combinators: `Decode.map`/`map2`/`map4`, `Decode.nullable` (JSON null → `Option`),
# `Decode.oneOf` (first decoder that succeeds — decode a union), `Decode.andThen`
# (a decoder chosen from an already-decoded value), `Decode.succeed`/`Decode.fail`.
'''),
    "compile_007_8ce467da": ("compile", '''
        let m = Map.ofList [(1, "one"), (2, "two"), (3, "three")]
        let empty = Map.isEmpty (Map.ofList [])
        let full = Map.isEmpty m
        let shouted = Map.toList (Map.map (fun k v -> String.concat v "!") m)
        let kept = Map.toList (Map.filter (fun k v -> k > 1) m)
        let keySum = Map.fold (fun acc k v -> acc + k) 0 m
        let any = Map.exists (fun k v -> v == "two") m
        let all = Map.forall (fun k v -> k > 0) m
        let joined = Map.toList (Map.union m (Map.ofList [(3, "THREE"), (4, "four")]))
        let split = Map.partition (fun k v -> k > 1) m
        let passing = Map.toList (fst split)
        let failing = Map.toList (snd split)
        '''),
    "compile_008_472123fd": ("compile", '''extern import asyncio
extern runAsync: Async a -> a = asyncio.run
module Html =
  let yield_ n = [n]
  let combine a b = List.concat a b
  let delay f = f ()
  let for_ xs f = List.collect f xs
let page rows = Html {
  yield "h1"
  for r in rows:
    yield f"tr {r}"
  yield "p"
}
print (page ["a", "b"])
let squares = seq {
  for x in [1, 2, 3]:
    let y = x * x
    yield y
  yield 100
}
print (Seq.toList squares)
let nested = seq { for x in [1, 2]: for y in Seq.ofList [10, 20]: yield x + y }
print (Seq.toList nested)
let pairs = seq { for (a, b) in [(1, 2), (3, 4)]: yield a + b }
print (Seq.toList pairs)
let check x = if x > 0 then Ok x else Error f"bad {x}"
let allGood xs = result {
  for x in xs:
    let! _ = check x
  return "all positive"
}
print (allGood [1, 2, 3])
print (allGood [1, -2, 3])
let main = async {
  for n in [1, 2]:
    do! Async.sleep 0.001
    print n
  return ()
}
runAsync main'''),
    "compile_009_d10008d8": ("compile", '''let slow n = async { do! Async.sleep 0.01  return n }
let main = async {
  let! xs = Async.parallel [slow 1, slow 2]
  let! first = Async.race [slow 3, slow 4]
  let! t = Async.timeout 0.5 (slow 5)
  let! v = Async.toThread (fun _ -> 41)
  let! r = Async.catch (slow 6)
  let total = match t:
    case Some n: n
    case None: 0
  let got = match r:
    case Ok n: n
    case Error e: String.len e.errorKind
  return List.sum xs + first + total + v + got
}'''),
    "compile_010_e29c34f1": ("compile", '''
        let xs = [3, 1, 4, 1, 5]
        let summed = List.map2 (fun a b -> a + b) [1, 2, 3] [10, 20]
        let ix = List.indexed ["a", "b"]
        let any = List.exists (fun x -> x > 4) xs
        let all = List.forall (fun x -> x > 0) xs
        let at = List.findIndex (fun x -> x == 4) xs
        let missing = List.findIndex (fun x -> x == 99) xs
        let desc = List.sortDescending xs
        let uniq = List.distinct xs
        let grouped = List.groupBy (fun x -> x % 2) [1, 2, 3, 4]
        '''),
    "native_011_dc5a7cfb": ("native", 'extern import asyncio\nextern runAsync: Async a -> a = asyncio.run\nextern type Reader\nextern type Writer\nextern type Server\nextern type Bytes\nextern startServer: (Reader -> Writer ->{e} Async unit) -> string -> int -> Async Server = asyncio.start_server\nextern openConnection: string -> int -> Async (Reader, Writer) = asyncio.open_connection\nextern readline: Reader -> Async Bytes = .readline()\nextern write: Writer -> Bytes -> unit = .write\nextern drain: Writer -> Async unit = .drain()\nextern closeWriter: Writer -> unit = .close()\nextern closeServer: Server -> unit = .close()\nextern encode: string -> Bytes = .encode()\nextern decode: Bytes -> string = .decode()\nlet shout reader writer = async {\n  let! line = readline reader\n  write writer (encode (String.upper (decode line)))\n  do! drain writer\n  closeWriter writer\n}\nlet main = async {\n  let! server = startServer shout "127.0.0.1" 47321\n  let! (reader, writer) = openConnection "127.0.0.1" 47321\n  write writer (encode "hello\\n")\n  do! drain writer\n  let! reply = Async.timeout 5.0 (readline reader)\n  print (reply |> Option.map (fun b -> String.strip (decode b)))\n  closeWriter writer\n  closeServer server\n}\nrunAsync main'),
    "compile_012_1b65af79": ("compile", '''
        let dropped = Seq.toList (Seq.drop 2 (Seq.ofList [1, 2, 3, 4]))
        let taken = Seq.toList (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))
        let skipped = Seq.toList (Seq.dropWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))
        let joined = Seq.toList (Seq.concat (Seq.ofList [1, 2]) (Seq.ofList [3]))
        let flat = Seq.toList (Seq.flatten (Seq.ofList [Seq.ofList [1, 2], Seq.ofList [3]]))
        let mapped = Seq.toList (Seq.collect (fun x -> Seq.ofList [x, x]) (Seq.ofList [1, 2]))
        let zipped = Seq.toList (Seq.zip (Seq.ofList [1, 2]) (Seq.ofList ["a", "b"]))
        let ix = Seq.toList (Seq.indexed (Seq.ofList ["a", "b"]))
        let uniq = Seq.toList (Seq.distinct (Seq.ofList [1, 1, 2, 1, 3]))
        let pairs = Seq.toList (Seq.pairwise (Seq.ofList [1, 2, 3]))
        let built = Seq.toList (Seq.init 4 (fun i -> i * i))
        '''),
    "compile_013_7525ec15": ("compile", '''let (|Answer|_|) o = o == Some 42
let classify o =
  let label =
    match o:
      case Answer: "answer"
      case Some n: String.fromInt n
      case None: "none"
  String.concat label "!"'''),
    "compile_014_6c4924f7": ("compile", '''type Handler = H (string ->{io} unit)
let h = H (fun s -> ())'''),
    "compile_015_9633f98b": ("compile", '''
        let some1 = Some 1
        let some2 = Some 2
        let none = List.head (List.drop 9 [1])
        let both = Option.map2 (fun a b -> a + b) some1 some2
        let missing = Option.map2 (fun a b -> a + b) some1 none
        let kept = Option.orElse some2 some1
        let fellBack = Option.orElse some2 none
        let flat = Option.flatten (Some (Some 5))
        let flatNone = Option.flatten (Some none)
        let listed = Option.toList some1
        let empty = Option.toList none
        let holds = Option.exists (fun x -> x > 0) some1
        let holdsNot = Option.exists (fun x -> x > 0) none
        '''),
    "compile_016_a8d226c5": ("compile", '''
        let doubles = Seq.toList (Seq.take 5 (Seq.initInfinite (fun i -> i * 2)))
        let powers = Seq.toList (Seq.take 4 (Seq.unfold (fun s -> if s > 100 then None else Some (s, s * 2)) 1))
        let firstBig = Seq.find (fun x -> x > 6) (Seq.initInfinite (fun i -> i * 2))
        '''),
    "compile_017_d2d4a7c1": ("compile", '''
        let s = Set.ofList [3, 1, 4, 1, 5]
        let empty = Set.isEmpty (Set.ofList [])
        let full = Set.isEmpty s
        let halved = List.sort (Set.toList (Set.map (fun x -> x % 2) s))
        let kept = List.sort (Set.toList (Set.filter (fun x -> x > 2) s))
        let total = Set.fold (fun acc x -> acc + x) 0 s
        let any = Set.exists (fun x -> x > 4) s
        let all = Set.forall (fun x -> x > 0) s
        let sub = Set.isSubset (Set.ofList [1, 3]) s
        let sup = Set.isSuperset s (Set.ofList [1, 3])
        let biggest = Set.max s
        let smallest = Set.min s
        let noMax = Set.max (Set.ofList [])
        let split = Set.partition (fun x -> x > 2) s
        let passing = List.sort (Set.toList (fst split))
        let failing = List.sort (Set.toList (snd split))
        '''),
    "compile_018_1bbda7c5": ("compile", '''let r = Ok 1
let a = Result.map (fun x -> x + 1) r
let b = Result.mapError (fun e -> e) r
let c = Result.bind (fun x -> Ok (x + 1)) r
let d = Result.withDefault 0 r
let e = Result.isOk r
let f = Result.isError r
let g = Result.toOption r'''),
    "native_019_d71deaf6": ("native", '''
        let f a =
          let g o =
            let before = a
            let (a, b) = (10, 20)
            before + a + b + o
          g 1
        let r = f 100
        '''),
    "compile_020_f8e508ce": ("compile", '''let a = Format.fixed 2 3.14159
let b = Format.thousands 2 1234567.5
let c = Format.percent 1 0.256
let d = Format.currency "$" 2 1234.5
let e = Format.grouped 1234567
let f = Format.padLeft 6 "0" "42"
let g = Format.padRight 6 "." "42"'''),
    "compile_021_a1c9636e": ("compile", '''extern parseInt : string -> int -> int = int(base=...)
let bare = parseInt
let partial = parseInt "ff"'''),
    "compile_022_24106978": ("compile", '\n        let empty = String.isEmpty ""\n        let full = String.isEmpty "a"\n        let at = String.get 1 "abc"\n        let past = String.get 9 "abc"\n        let thrice = String.repeat 3 "ab"\n        let none = String.repeat 0 "ab"\n        let left = String.trimStart "  hi  "\n        let right = String.trimEnd "  hi  "\n        let lines = String.splitLines "a\\nb\\nc\\n"\n        let backwards = String.rev "abc"\n        let joined = String.ofList ["a", "b", "c"]\n        let roundTrip = String.ofList (String.toList "xyz")\n        '),
    "compile_023_386bcfd7": ("compile", '''let hd xs =
           match List.head xs:
             case Some h: h
             case None: 0
         let g i xs = 1 + (match List.get (i + 1) xs:
           case Some (a, b): a + b
           case None: 0)
         let w m = match Map.tryFind 1 m:
           case Some _: 1
           case None: 0'''),
    "native_024_65364281": ("native", 'type Placed = { letter: string, score: int }\ntype Player = Ann | Bob\ntype Msg = Hello Player | Move string | Resign\ntype Tree = Leaf | Node Tree int Tree\ntype View = { board: Map (int, int) Placed, players: List Player, turn: Option Player, last: Msg, tree: Tree, pair: (string, float), tags: Set string }\nlet view = View {\n  board = Map.ofList [((1, 2), Placed { letter = "Q", score = 10 })],\n  players = [Ann, Bob],\n  turn = Some Bob,\n  last = Move "K11 a QUIZ",\n  tree = Node Leaf 1 (Node Leaf 2 Leaf),\n  pair = ("x", 1.5),\n  tags = Set.ofList ["a"]\n}\nlet wire = Encode.auto view\nprint wire\nlet back = Decode.decodeString Decode.auto wire\nmatch back:\n  case Ok v: print (v == view)\n  case Error e: print f"failed: {e.errorKind} {e.errorMessage}"\nlet showMsg m =\n  match m:\n    case Hello p: f"hello {p}"\n    case Move s: f"move {s}"\n    case Resign: "resign"\nlet decodeMsg s =\n  match Decode.decodeString Decode.auto s:\n    case Ok m: showMsg m\n    case Error e: f"error {e.errorKind}: {e.errorMessage}"\nprint (decodeMsg "{\\"type\\": \\"Resign\\"}")\nprint (decodeMsg "{\\"type\\": \\"Hello\\", \\"fields\\": [{\\"type\\": \\"Ann\\"}]}")\nprint (decodeMsg "{\\"type\\": \\"Nope\\"}")\nprint (decodeMsg "[1, 2]")\nprint (decodeMsg "{\\"type\\": \\"Move\\", \\"fields\\": [1]}")'),
    "compile_025_64577414": ("compile", '''let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)
let f n =
  match n:
    case Small _ | Big _: 1'''),
    "compile_026_1b3f059d": ("compile", '''
        let ok1 = Ok 1
        let ok2 = Ok 2
        let bad = Error "boom"
        let both = Result.map2 (fun a b -> a + b) ok1 ok2
        let failed = Result.map2 (fun a b -> a + b) bad ok2
        let kept = Result.orElse ok2 ok1
        let fellBack = Result.orElse ok2 bad
        let listed = Result.toList ok1
        let empty = Result.toList bad
        '''),
    "compile_027_cf04a5f3": ("compile", '''let show r =
  match r:
    case Ok v: f"ok: {v}"
    case Error e: e.errorMessage
let tagOf = Decode.oneOf [Decode.map (fun b -> "bool") Decode.bool, Decode.map (fun n -> "int") Decode.int]
let firstMatch = show (Decode.decodeString tagOf "true")
let secondMatch = show (Decode.decodeString tagOf "5")
let allFail = show (Decode.decodeString (Decode.oneOf [Decode.string, Decode.map (fun b -> "b") Decode.bool]) "5")
'''),
    "compile_028_0e31827d": ("compile", '''type Point = { x: int, y: int }

let (name, score) = ("ada", 10)
let (first, (second, third)) = (1, (2, 3))
let Point { x, y } = Point { x = 3, y = 4 }

let swap p =
  let (a, b) = p
  (b, a)

print f"{name} scored {score}"
print (first + second + third)
print (x * y)
print (swap (1, 2))'''),
    "compile_029_25560ba2": ("compile", '''
        type Point = { x : int, y : int }
        let f y p q =
          let a =
            match p:
              case Point { x = 0, y }: y
              case Point { x }: x + y
          let b =
            match q:
              case (0, y) | (y, 0): y
              case (_, _): y
          a + b
        let r = f 1000 (Point { x = 0, y = 2 }) (0, 3)
        let s = f 1000 (Point { x = 4, y = 2 }) (7, 8)
        '''),
    "compile_030_6b1df06c": ("compile", '''
        let first = Seq.head (Seq.ofList [7, 8])
        let none = Seq.head (Seq.ofList [])
        let empty = Seq.isEmpty (Seq.ofList [])
        let full = Seq.isEmpty (Seq.ofList [1])
        let n = Seq.len (Seq.ofList [1, 2, 3])
        let any = Seq.exists (fun x -> x > 2) (Seq.ofList [1, 2, 3])
        let all = Seq.forall (fun x -> x > 0) (Seq.ofList [1, 2, 3])
        let has = Seq.contains 2 (Seq.ofList [1, 2, 3])
        let total = Seq.sum (Seq.ofList [1, 2, 3])
        let found = Seq.find (fun x -> x > 1) (Seq.ofList [1, 2, 3])
        let missing = Seq.find (fun x -> x > 9) (Seq.ofList [1, 2, 3])
        '''),
    "compile_031_362db13f": ("compile", '''extern import asyncio
extern runAsync: Async a -> a = asyncio.run
extern pause: float -> Async unit = asyncio.sleep
extern sleepThen: float -> a -> Async a = asyncio.sleep
let pauses = [0.0, 0.0] |> List.map pause
let values = [1, 2] |> List.map (sleepThen 0.0)
let main = async {
  for p in pauses:
    do! p
    do! p
  for v in values:
    let! a = v
    let! b = v
    print (a + b)
  return ()
}
runAsync main'''),
    "compile_032_589cd6cc": ("compile", '''let a = Set.iter (fun x -> print x) (Set.ofList [1])
let b = Map.iter (fun k v -> print v) (Map.ofList [(1, 2)])'''),
    "native_033_89691dde": ("native", '''let a k m =
           match Map.tryFind k m:
             case Some 0: "zero"
             case Some _: "other"
             case None: "none"
         let b k m =
           match Map.tryFind k m:
             case Some v if v > 0: v
             case _: 0
         let c f = match f 1:
           case Some v: v
           case None: 0'''),
    "compile_034_10bb0283": ("compile", '''let r = List.choose (fun x -> if x > 1 then Some (x * 10) else None) [1, 2, 3]'''),
    "compile_035_1efca1c0": ("compile", '''extern import threading
extern type Thread
extern newThread: unit -> (unit ->{io} unit) -> Thread = threading.Thread(daemon = true, target = ...)
let t = newThread () (fun _ -> print "hi")'''),
    "compile_036_24e13129": ("compile", '''
        let xs = [3, 1, 4, 1, 5]
        let first = List.head xs
        let none = List.head (List.drop 9 [1])
        let rest = List.tail xs
        let taken = List.take 2 xs
        let dropped = List.drop 3 xs
        let overTake = List.take 99 xs
        let negTake = List.take (-1) xs
        let split = List.splitAt 2 xs
        '''),
    "compile_037_da75a0bf": ("compile", '''let p l = List.findIndex ((==) l)
         let q l rack = List.findIndex (fun y -> y > l) rack
         let r rack = List.findIndex (fun y -> y == y) rack
         let s l rack = List.exists (fun l -> l == l) rack'''),
    "native_038_2688aadb": ("native", '''let step acc x =
  match acc:
    case (m, l, s): (Map.add x x m, List.concat l [x], Set.add x s)
let dseed = Map.empty
let lseed = []
let sseed = Set.empty
let r = List.fold step (dseed, lseed, sseed) [1, 2]
let out = match r: case (m, l, s): (Map.toList m, l, Set.toList s)
let origs = (Map.len dseed, List.len lseed, Set.len sseed)'''),
    "compile_039_395b0e2b": ("compile", '''let finished acc = async { return acc }
let collect n acc =
  async {
    return! (if n == 0 then finished acc else collect (n - 1) (List.concat acc [fun k -> n]))
  }'''),
    "compile_040_eef2280b": ("compile", '''measure m
measure s

type Run = { name: string, distance: float, time: float }

let runDecoder =
  Decode.map3 (fun n d t -> Run { name = n, distance = d, time = t })
    (Decode.field "name" Decode.string)
    (Decode.field "distance" Decode.float)
    (Decode.field "time" Decode.float)

let input = """[
  {"name": "ada", "distance": 100.0, "time": 20.0},
  {"name": "bo", "distance": 140.0, "time": 30.0}
]"""

let report =
  match Decode.decodeString (Decode.list runDecoder) input:
    case Ok runs:
      let names = runs |> List.map (fun r -> r.name) |> String.join ", "
      let dist = runs |> List.fold (fun a r -> a + r.distance * 1.0<m>) 0.0<m>
      let time = runs |> List.fold (fun a r -> a + r.time * 1.0<s>) 0.0<s>
      let avg = dist / time
      f"{names}: average speed {avg} m/s over {List.len runs} runs"
    case Error e: f"could not read input ({e.errorKind})"

print report
'''),
    "compile_041_194e09a7": ("compile", '''let a = Option.forall (fun x -> x > 0) (Some 1)
let b = Option.contains 1 (Some 1)
let c = Result.exists (fun x -> x > 0) (Ok 1)
let d = Result.forall (fun x -> x > 0) (Ok 1)
let e = Result.contains 1 (Ok 1)'''),
    "compile_042_04ff71d4": ("compile", '''let m = Map.add "a" 1 (Map.add "b" 2 Map.empty)
let v = Map.findOr "a" 0 m
let o = Map.tryFind "a" m
let m2 = Map.remove "b" m
let has = Map.contains "a" m2
let n = Map.len m2
let ks = Map.keys m
let vs = Map.values m'''),
    "compile_043_98df6467": ("compile", '''type P = { name: string, age: int }
             let ps = [P { name = "a", age = 2 }]
             let byAge = List.sortBy (fun p -> p.age) ps
             let oldest = List.maxBy (fun p -> p.age) ps'''),
    "compile_044_52f84a83": ("compile", '''let a l rack = List.findIndex ((==) l) rack
         let b l rack = List.find ((==) l) rack
         let c l rack = List.exists ((==) l) rack
         let d l rack = List.findIndex (fun y -> y == l) rack
         let e l rack = List.findIndex (fun y -> l == y) rack'''),
    "compile_045_7c6c439a": ("compile", '''let opt r =
  match r:
    case Ok o:
      match o:
        case Some x: f"some {x}"
        case None: "none"
    case Error e: e.errorKind
let onNull = opt (Decode.decodeString (Decode.nullable Decode.int) "null")
let onValue = opt (Decode.decodeString (Decode.nullable Decode.int) "5")
'''),
    "compile_046_dfaf1de9": ("compile", '''type Expr = Num int | Add Expr Expr
type Point = { x: int, y: int }
opaque type Id = string
let simp e =
  match e:
    case Add (Num 0) b: b
    case Add a (Num 0): a
    case other: other
let quad p =
  let q =
    match p:
      case Point { x = 0, y = 0 }: "origin"
      case Point { x = 0 }: "y axis"
      case Point { x, y } as whole: f"{x},{y} {whole.x}"
  q
let name i = match (i, true):
  case (Id "root", true): "admin"
  case (Id s, _): s
print (simp (Add (Num 0) (Num 7)))
print (simp (Add (Num 5) (Num 0)))
print (quad (Point { x = 0, y = 0 }))
print (quad (Point { x = 0, y = 3 }))
print (quad (Point { x = 2, y = 3 }))
print (name (Id "root"))
print (name (Id "ada"))'''),
    "native_047_4d801d79": ("native", '''let report o =
  match o:
    case Some n: print n
    case None: print "none"
  print "done"
report (Some 1)'''),
    "compile_048_d71d523d": ("compile", '''extern import asyncio
extern runAsync: Async a -> a = asyncio.run
let finished count = async { return count }
let countdown n acc =
  async {
    return! (if n == 0 then finished acc else countdown (n - 1) (acc + n))
  }
let tally xs =
  let mut total = 0
  let add x = total <- total + x
  List.iter add xs
  total
print (runAsync (countdown 4 0))
print (tally [1, 2, 3])'''),
    "native_049_a386aa77": ("native", '''let f o =
  match o:
    case Some (1 | 2): "low"
    case Some ((3 | 4) as n): f"mid {n}"
    case Some _: "high"
    case None: "none"
print (f (Some 2))
print (f (Some 4))
print (f (Some 9))
print (f None)'''),
    "compile_050_4af1df14": ("compile", '''let (|DivisibleBy|_|) d n = n % d == 0
let f n =
  match n:
    case DivisibleBy 3: "fizz"
    case _: "n"'''),
    "compile_051_9a5d8b08": ("compile", '''let bump n = n + 100
let useBump x = bump x
let useIt =
  let bump = 0
  useBump 5
let after = useBump 7'''),
    "compile_052_0225ff71": ("compile", '''let step acc x =
  match acc:
    case (cur, groups):
      if x == 0 then ([], List.concat groups [cur])
      else (List.concat cur [x], groups)
let out = match List.fold step ([], []) [1, 2, 0, 3, 0]: case (cur, groups): (cur, groups)'''),
    "compile_053_09f7e91e": ("compile", '''let s = Set.ofList [1, 2, 3]
let s2 = Set.add 4 s
let s3 = Set.remove 1 s2
let has = Set.contains 2 s3
let n = Set.len s3
let u = Set.union s s2
let i = Set.intersect s s2
let d = Set.difference s s2
let xs = Set.toList (Set.union s Set.empty)'''),
    "compile_054_460f88bd": ("compile", '''let check x = if x > 0 then Ok () else Error "neg"
let v = result { do! check 1 }
let w = result {
  let! a = Ok 2
  print a
  do! check (0 - a)
}
print v
print w'''),
    "compile_055_8e2cad7a": ("compile", '''let f x = 1 < x < 10
let g = 1 == 1 == 1'''),
    "compile_056_c308bb3e": ("compile", '''let go = Option.iter (fun x -> print x) (Some 1)'''),
    "compile_057_0be9f454": ("compile", '''let names = ["ada", "grace", "alan"]

let headline names =
  names
  |> List.map ?upper
  |> String.join ", "

names |> headline |> print'''),
    "compile_058_108d962f": ("compile", '''extern g : string -> a = gzip.open(compresslevel=9, buffering=-1, text=true, ratio=2.5)
let f path = g path'''),
    "native_059_14dccec2": ("native", '# The SAME timetable as chippenham.pyfun, but the streaming boundary is a native\n# Python loop (nr_stream.py) instead of a Pyfun `Seq.fold`. The domain engine below\n# is byte-for-byte identical; only the I/O at the top differs.\n#\n#   cargo run -- compile examples/interop/network-rail/chippenham_fast.pyfun \\\n#       -o examples/interop/network-rail/chippenham_fast.py\n#   PYTHONPATH=examples/interop/network-rail \\\n#       python examples/interop/network-rail/chippenham_fast.py\n#\n# Why keep this alongside the pure-Pyfun version? Because it\'s ~15x faster on the\n# real feed (~5s vs ~75s for ~20M lines), and that gap is the whole lesson: the hot\n# per-line loop belongs in a tight, C-backed Python `for` loop, not in a Pyfun fold\n# that pays a call per element. Pyfun\'s job is the typed engine; Python\'s optimized\n# libraries do the grinding. `extern` is the boundary that lets you have both —\n# leverage the fast thing that already exists rather than re-emulate it in Pyfun.\n\nextern scan: string -> ( (Map string string)\n                       , (List ( string, string, string\n                               , (List (string, string, string)) )) )\n       = nr_stream.scan\nextern writeUtf8: string -> string -> int = nr_stream.write_utf8\n\ntype Stop = { tiploc: string, arr: string, dep: string }\ntype Run  = { uid: string, days: string, stp: string, stops: List Stop }\ntype Leg  = { dest: string, finalDest: string, rdays: string, depMin: int, arrMin: int, jt: int, via: List string }\n\nlet dataFile = "examples/interop/network-rail/sample.ndjson"\nlet outFile  = "examples/interop/network-rail/chippenham-routes.md"\n\n# --- shape the boundary\'s tuples into typed records ---\nlet toStop t =\n  match t:\n    case (tp, a, d): Stop { tiploc = tp, arr = a, dep = d }\n\nlet toRun r =\n  match r:\n    case (uid, days, stp, stops):\n      Run { uid = uid, days = days, stp = stp, stops = List.map toStop stops }\n\n# A stop is a public calling point iff it advertises a public time.\nlet calls s = (s.arr != "" and s.arr != "0000") or (s.dep != "" and s.dep != "0000")\n\nlet toMin hhmm =\n  match (String.toInt (String.slice 0 2 hhmm), String.toInt (String.slice 2 4 hhmm)):\n    case (Some h, Some m): h * 60 + m\n    case _: -1\n\nlet fmt2 n = if n < 10 then f"0{n}" else f"{n}"\nlet showTime m = f"{fmt2 (m // 60)}:{fmt2 (m % 60)}"\n\nlet jtime dep arr =\n  let d = arr - dep\n  if d < 0 then d + 1440 else d\n\nlet fromChippenham stops =\n  match stops:\n    case []: None\n    case [s, *rest]:\n      if s.tiploc == "CHIPNHM" and calls s then Some (s.dep, rest)\n      else fromChippenham rest\n\nlet lastTiploc stops =\n  match stops:\n    case []: ""\n    case [s]: s.tiploc\n    case [_, *rest]: lastTiploc rest\n\nlet walkLegs days term depM via stops =\n  match stops:\n    case []: []\n    case [s, *rest]:\n      if calls s then\n        let arrM = toMin s.arr\n        let onward = List.concat via [s.tiploc]\n        if arrM < 0 then walkLegs days term depM onward rest\n        else\n          let leg = Leg { dest = s.tiploc, finalDest = term, rdays = days, depMin = depM,\n                          arrMin = arrM, jt = jtime depM arrM, via = via }\n          List.concat [leg] (walkLegs days term depM onward rest)\n      else walkLegs days term depM via rest\n\nlet legsOfRun r =\n  if r.stp == "C" then []\n  else\n    match fromChippenham r.stops:\n      case None: []\n      case Some (chippDep, downstream):\n        let depM = toMin chippDep\n        if depM < 0 then []\n        else walkLegs r.days (lastTiploc downstream) depM [] downstream\n\nlet runsOn day days = String.slice day (day + 1) days == "1"\n\nlet dedupLegs legs =\n  let step acc leg =\n    match acc:\n      case (seen, out):\n        let k = f"{leg.depMin}|{leg.dest}"\n        match Map.tryFind k seen:\n          case Some _: (seen, out)\n          case None: (Map.add k true seen, List.concat out [leg])\n  match List.fold step (Map.empty, []) legs:\n    case (_, out): out\n\nlet groupByDest acc leg =\n  Map.add leg.dest (List.concat (Option.withDefault [] (Map.tryFind leg.dest acc)) [leg]) acc\n\nlet insertByDep leg sorted =\n  match sorted:\n    case []: [leg]\n    case [x, *rest]:\n      if leg.depMin <= x.depMin then List.concat [leg] sorted\n      else List.concat [x] (insertByDep leg rest)\n\nlet sortLegs legs = List.fold (fun acc l -> insertByDep l acc) [] legs\n\nlet minOf xs =\n  match xs:\n    case []: 0\n    case [x]: x\n    case [x, *rest]:\n      let m = minOf rest\n      if x < m then x else m\n\nlet maxOf xs =\n  match xs:\n    case []: 0\n    case [x]: x\n    case [x, *rest]:\n      let m = maxOf rest\n      if x > m then x else m\n\n# --- title-casing (feed descriptions are UPPERCASE) ---\nlet capFirst chars =\n  match chars:\n    case []: []\n    case [c, *rest]:\n      if String.upper c != c then List.concat [String.upper c] rest\n      else List.concat [c] (capFirst rest)\n\nlet capWord w = String.join "" (capFirst (String.toList w))\nlet titleHyphen w = String.join "-" (List.map capWord (String.split "-" w))\nlet titleCase name = String.join " " (List.map titleHyphen (String.split " " (String.lower name)))\n\n# --- rendering (Markdown) ---\nlet nameOf names tp = titleCase (Option.withDefault tp (Map.tryFind tp names))\nlet plural n word = if n == 1 then f"{n} {word}" else f"{n} {word}s"\nlet rangeStr lo hi = if lo == hi then f"{lo} min" else f"{lo}-{hi} min"\n\nlet renderService names leg =\n  let stopStr =\n    match leg.via:\n      case []: "direct"\n      case _:\n        let viaStr = String.join ", " (List.map (nameOf names) leg.via)\n        f"via {viaStr}"\n  let onward = if leg.dest == leg.finalDest then "" else f" _(to {nameOf names leg.finalDest})_"\n  f"- **{showTime leg.depMin} → {showTime leg.arrMin}** · {leg.jt} min · {stopStr}{onward}"\n\nlet renderGroup names g =\n  match g:\n    case (dest, legs):\n      let times = List.map (fun l -> l.jt) legs\n      let tr = plural (List.len legs) "train"\n      let header = f"### {nameOf names dest} — {tr}, {rangeStr (minOf times) (maxOf times)}"\n      let body = String.join "\\n" (List.map (renderService names) (sortLegs legs))\n      f"{header}\\n\\n{body}"\n\nlet daySection names label day allLegs =\n  let legs = dedupLegs (List.filter (fun l -> runsOn day l.rdays) allLegs)\n  let pairs = List.map (fun g -> match g: case (dest, ls): (nameOf names dest, renderGroup names g))\n                       (Map.toList (List.fold groupByDest Map.empty legs))\n  let body = String.join "\\n\\n" (List.map (fun p -> match p: case (nm, txt): txt) (List.sort pairs))\n  f"## {label}\\n\\n{body}"\n\nlet buildReport names raw =\n  let allLegs = List.fold (fun acc r -> List.concat acc (legsOfRun r)) [] (List.map toRun raw)\n  let intro = "# Direct services from Chippenham\\n\\n_Every station reachable directly (no change) from Chippenham, grouped by destination, in departure order. Counts reflect the weekly day-of-week pattern of permanent + new schedules minus cancellations; a specific date may differ._"\n  let wd = daySection names "Monday–Friday (representative day: Tuesday)" 1 allLegs\n  let sa = daySection names "Saturday" 5 allLegs\n  let su = daySection names "Sunday" 6 allLegs\n  String.join "\\n\\n" [intro, wd, sa, su]\n\nlet _ =\n  match scan dataFile:\n    case (names, raw): writeUtf8 outFile (buildReport names raw)\n\nprint (f"Wrote Markdown direct Chippenham services to {outFile}")\n'),
    "compile_060_3aa4ce27": ("compile", '''let go = Seq.iter (fun x -> print x) (Seq.ofList [1])'''),
    "compile_061_5aa361df": ("compile", '''let step acc x =
  let peek u = Map.len acc
  Map.add x (peek 0) acc
let out = Map.toList (List.fold step Map.empty [1, 2, 3])'''),
    "compile_062_5e213bb4": ("compile", '''let xs = seq { yield 1  yield! (seq { yield 2 }) }'''),
    "compile_063_beddc72b": ("compile", '''extern type P
extern toPath : string -> P = pathlib.Path
extern writeText : P -> string -> string -> int = .write_text(encoding=...)
let partial = writeText (toPath "a.txt") "body"'''),
    "compile_064_5d033227": ("compile", '''extern myAbs: unit -> int -> int = abs
extern pick: int -> unit -> int -> int = max
let fromNeg = myAbs ()
let lifted = pick 4
print (fromNeg (-7))
print (lifted () 2)'''),
    "compile_065_63a435a9": ("compile", '''
        type Cell = { row: int, col: int, letter: string }
        type Pair = { left: Cell, right: Cell }
        let describe (Cell { letter, row }) = letter
        let leftLetter (Pair { left = Cell { letter } }) = letter
        let both (Pair { left, right }) = (left.letter, right.letter)
        let a = Cell { row = 1, col = 2, letter = "A" }
        let b = Cell { row = 3, col = 4, letter = "B" }
        let p = Pair { left = a, right = b }
        let one = describe a
        let deep = leftLetter p
        let pairOf = both p
        '''),
    "compile_066_6dd904ac": ("compile", '''
        let f x =
          let k a b = fun c -> a + b + c
          k 1 2 x
        let r = f 3
        '''),
    "compile_067_c6043557": ("compile", '''extern openText : string -> int -> Seq string = builtins.open(mode="rt")
let bare = openText
let partial = openText "a.txt"'''),
    "compile_068_97797662": ("compile", '''extern import os.path
extern joinp : string -> string -> string = os.path.join
let os = 1
print (joinp "a" "b")'''),
    "compile_069_b5d4bb5c": ("compile", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let describe n =
  match n:
    case Even if n > 100: "big even"
    case Even: "even"
    case Odd: "odd"
let a = describe 200
let b = describe 4
let c = describe 7'''),
    "compile_070_d5c7188b": ("compile", '''let (|Tag|Untag|) n =
  print "eval"
  if n > 0 then Tag n else Untag
let r =
  match 5:
    case Tag v: v
    case Untag: 0
print r'''),
    "compile_071_0b9fa9c8": ("compile", '''module M =
    let (w, h) = (3, 4)
let r = M.w + M.h'''),
    "compile_072_97a56981": ("compile", 'let who = "Ada"\nlet score = 41\n\nlet line = f"{who} scored {score} ({String.upper who})"\nlet debug = f"{score=}"\nlet braces = f"{{literal braces}} around {score}"\nlet winPath = r"C:\\Users\\pyfun\\data.csv"\nlet banner = """== pyfun ==\na "quoted" word"""\nlet emoji = "hi \\u{1F600}"\n\nprint line\nprint debug\nprint braces\nprint winPath\nprint banner\nprint (String.len "café")\nprint (String.len emoji)'),
    "compile_073_09959aab": ("compile", '''
        let f o p =
          option {
            do! p
            let! x = o
            return! (if x > 0 then Some (x * 2) else None)
          }
        let a =
          match f (Some 3) (Some ()):
            case Some n: n
            case None: 0
        let b =
          match f (Some 3) None:
            case Some n: n
            case None: 0
        let c =
          match f (Some 0) (Some ()):
            case Some n: n
            case None: 0
        '''),
    "py311_074_ffaab871": ("py311", '''let (|Even|Odd|) n = Even'''),
    "compile_075_234bb7d5": ("compile", '''let _None_ = 1
let n = None
let o = Map.tryFind 1 Map.empty'''),
    "compile_076_65bb4e7d": ("compile", '''let xs = [1, 2, 3, 4]
let doubled = List.map (fun x -> x * 2) xs
let small = List.filter (fun x -> x < 3) xs
let total = List.fold (fun a b -> a + b) 0 xs
let n = List.len xs
let s = List.sum xs
let r = List.rev xs
let q = List.range 1 4'''),
    "compile_077_799fdeb3": ("compile", '''let step s x = Set.remove (x - 1) (Set.add x s)
let out = Set.toList (List.fold step Set.empty [1, 2, 3])'''),
    "native_078_dfaf1de9": ("native", '''type Expr = Num int | Add Expr Expr
type Point = { x: int, y: int }
opaque type Id = string
let simp e =
  match e:
    case Add (Num 0) b: b
    case Add a (Num 0): a
    case other: other
let quad p =
  let q =
    match p:
      case Point { x = 0, y = 0 }: "origin"
      case Point { x = 0 }: "y axis"
      case Point { x, y } as whole: f"{x},{y} {whole.x}"
  q
let name i = match (i, true):
  case (Id "root", true): "admin"
  case (Id s, _): s
print (simp (Add (Num 0) (Num 7)))
print (simp (Add (Num 5) (Num 0)))
print (quad (Point { x = 0, y = 0 }))
print (quad (Point { x = 0, y = 3 }))
print (quad (Point { x = 2, y = 3 }))
print (name (Id "root"))
print (name (Id "ada"))'''),
    "compile_079_6cbbfd25": ("compile", '''
        let f flag =
          let count = 1
          let y =
            if flag then
              let mut count = 0
              let bump u = count <- count + u
              bump 4
              bump 5
              count
            else 0
          count + y
        let r = f true
        '''),
    "compile_080_b2491cdc": ("compile", '''let step m x = Map.remove x (Map.add (x + 1) x m)
let out = Map.toList (List.fold step Map.empty [1, 2, 3])'''),
    "compile_081_b94e46b2": ("compile", '''let dec = Decode.andThen (fun n -> Decode.succeed (n + 1)) Decode.int
let show r =
  match r:
    case Ok v: f"ok: {v}"
    case Error e: e.errorKind
let out = show (Decode.decodeString dec "41")
'''),
    "py311_082_5789f666": ("py311", '''let (|Answer|_|) o = o == Some 42
let f o =
  match o:
    case Some x if x > 100: "big"
    case Answer: "answer"
    case _: "other"'''),
    "compile_083_6e833fe2": ("compile", '''let build combiner xs =
  let step acc x = List.concat acc [x + 100]
  (fun step -> List.fold step [] xs) combiner
let out = build (fun acc x -> List.concat acc [x * 2]) [1, 2, 3]'''),
    "compile_084_81071197": ("compile", '''
        let collect n acc =
          if n == 0 then acc
          else collect (n - 1) (List.concat acc [fun k -> n])
        let fns = collect 3 []
        let values = List.map (fun f -> f 0) fns
        '''),
    "compile_085_9745dfcd": ("compile", '''
        let n = 5
        let f u =
          option {
            let m = n + 1
            let! n = Some 2
            return n + m
          }
        let r = f 0
        '''),
    "compile_086_49f359b7": ("compile", '''import Geometry
import Store

let floor = Geometry.area 4 5
let nine = Geometry.square 3
let widen = Geometry.area 10
let strip = widen 2

let hit = Store.lookup 1 |> Option.withDefault 0
let miss = Store.lookup 9 |> Option.withDefault 0

print floor
print nine
print strip
print hit
print miss'''),
    "native_087_8c48dc36": ("native", '''type Shape = Circle float | Rect float float | Dot
let describe s =
  match s:
    case Circle r if r > 10.0: "big circle"
    case Circle r: f"circle {r}"
    case Rect w h: f"rect {w * h}"
    case Dot: "dot"
print (describe (Circle 20.0))
print (describe (Circle 1.5))
print (describe (Rect 2.0 3.0))
print (describe Dot)'''),
    "compile_088_9854423e": ("compile", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let f n =
  match n:
    case 0: 0
    case Even: 2
    case Odd: 1
    case _: 9'''),
    "compile_089_a6c88fc6": ("compile", '''type Shape = Circle float | Square float
type Point = { x: int, y: int }
let area s =
  match s:
    case Circle r: 3.0 * r * r
    case Square w: w * w
let shift p dx = { p with x = p.x + dx }
let names xs = List.map (fun s -> String.upper s) xs
let first xs = List.head xs
let apply f x = f x
print (area (Square 2.0))
print (shift (Point { x = 1, y = 2 }) 3).x
print (names ["a"])
print (first [1])
print (apply (fun n -> n + 1) 1)'''),
    "compile_090_bf0fe1bb": ("compile", '''let w xs =
  match List.findIndex ((==) 2) xs:
    case Some i: i
    case other: -1'''),
    "compile_091_c0e33399": ("compile", '''let f = String.contains "x"
         let r = List.filter f ["xy", "ab"]'''),
    "compile_092_d8ae6398": ("compile", '''let show r =
  match r:
    case Ok v: f"ok: {v}"
    case Error e: f"{e.errorKind}: {e.errorMessage}"
let s = show (Decode.decodeString (Decode.succeed 42) "0")
let failed = show (Decode.decodeString (Decode.fail "boom") "0")
'''),
    "compile_093_f82b9661": ("compile", '''type Color = Red | Green | Blue
let r = [Red, Green] < [Red, Blue]'''),
    "compile_094_45554439": ("compile", '''
        let g = String.concat "Hello, " "World"
        let up = String.upper g
        let n = String.len g
        let parts = String.split ", " g
        let joined = String.join "/" parts
        let has = String.contains "World" g
        let r = String.replace "o" "0" g
        '''),
    "compile_095_f3b205b7": ("compile", '''extern import numpy as np
extern zeros : int -> string = np.zeros
let np = 1
print (zeros 3)'''),
    "compile_096_fcbe138e": ("compile", '''let some = Some 5
let none = None
let a = Option.withDefault 0 some
let b = Option.withDefault 0 none
let c = Option.isSome some
let d = Option.isNone none
let e = Option.map (fun x -> x + 1) some'''),
    "native_097_238e038a": ("native", '''extern runAsync: Async a -> a = asyncio.run
let check n = if n > 0 then Ok n else Error "negative"
let describe n =
  async {
    return! (match check n:
      case Ok v: async { return f"ok {v}" }
      case Error why: async { return why })
  }
print (runAsync (describe 3))
print (runAsync (describe (0 - 1)))'''),
    "compile_098_242ce8a5": ("compile", '''
        let addAll ys =
          let pair = fun a b -> a + b
          List.map (pair 10) ys
        let r = addAll [1, 2]
        '''),
    "compile_099_3bda5375": ("compile", '''
        opaque type UserId = string
        let total =
          ["ab", "c"]
          |> List.map UserId
          |> List.fold (fun acc u ->
            match u:
                case UserId s: acc + String.len s) 0
        '''),
    "py311_100_fedffb51": ("py311", '''1e'''),
    "native_101_144ffbc1": ("native", '''type Callbacks = { onData: string ->{io, async} unit }
'''),
    "native_102_25560ba2": ("native", '''
        type Point = { x : int, y : int }
        let f y p q =
          let a =
            match p:
              case Point { x = 0, y }: y
              case Point { x }: x + y
          let b =
            match q:
              case (0, y) | (y, 0): y
              case (_, _): y
          a + b
        let r = f 1000 (Point { x = 0, y = 2 }) (0, 3)
        let s = f 1000 (Point { x = 4, y = 2 }) (7, 8)
        '''),
    "compile_103_3f3ce1ff": ("compile", '''
        let f x o =
          let r =
            match o:
              case Some x: List.map (fun x -> x + 1) x
              case None: []
          List.len r + x
        let r = f 10 (Some [1, 2, 3])
        '''),
    "compile_104_5310c020": ("compile", '"a\\rb"'),
    "compile_105_5c978e49": ("compile", '''let (|Empty|_|) xs = List.isEmpty xs
let f xs =
  match xs:
    case Empty: 0
    case [x]: x
    case _: 1'''),
    "compile_106_5ee7b7e0": ("compile", '''let g o =
  match o:
    case Some x if x > 10: 1
    case _ if false: 2
    case None: 3
    case Some _: 4'''),
    "compile_107_7b56d007": ("compile", '''let nats = Seq.range 0 1000000
let squares = Seq.toList (Seq.take 5 (Seq.map (fun x -> x * x) nats))
let evens = Seq.toList (Seq.take 3 (Seq.filter (fun x -> x // 2 * 2 == x) nats))
let total = Seq.fold (fun acc x -> acc + x) 0 (Seq.ofList [1, 2, 3, 4])'''),
    "compile_108_7df4d999": ("compile", '''let shadow b xs = List.map ((+) b) xs'''),
    "compile_109_8207913e": ("compile", '''let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]
let out = acc'''),
    "compile_110_8b0bc856": ("compile", '''let check x = if x > 0 then Ok x else Error "neg"
let v = result {
  let! a = check 1
  print a
}
print v
let o = option { print 2 }
print o
let e = result {
  let! a = check (0 - 1)
  print a
}
print e'''),
    "compile_111_a7c2e36c": ("compile", '''let cap acc x =
  match acc:
    case (m, fs): (Map.add x x m, List.concat fs [fun u -> Map.len m])
let out = match List.fold cap (Map.empty, []) [1, 2]: case (m, fs): List.map (fun f -> f 0) fs'''),
    "py311_112_a98ca42b": ("py311", '''
        let s = "a}b"
        let r = f"contains: {String.contains "}" s}"
        let brace = f"lit {{x}} and {String.contains "}" s}"
        '''),
    "compile_113_cc866459": ("compile", '"""a\\tb\\u{e9}"""'),
    "compile_114_ddd6e809": ("compile", '''
        let f flag n =
          let go k = k * 100
          let y =
            if flag then
              let go k = if k == 0 then 0 else k + go (k - 1)
              go n
            else 0
          y + go 1
        let r = f true 3
        '''),
    "compile_115_eed57be7": ("compile", '''extern type C
extern ping: C -> unit -> string = .m()
let f c = ping c ()'''),
    "compile_116_1d69fed4": ("compile", '''# sqlite3 — a stateful, method-based (OOP) library, called safely from Pyfun.
#
#   pyfun run examples/interop/sqlite_query.pyfun
#
# Two patterns bridge an object-oriented library: an `extern type` for each opaque
# handle (a Connection/Cursor Pyfun never looks inside), and instance-method externs
# (`= .method()`) that call a method on their first argument — the receiver.

extern type Conn
extern type Cursor

extern connect: string -> Conn = sqlite3.connect        # a module function
extern execute: Conn -> string -> Cursor = .execute()   # conn.execute(sql)
extern fetchall: Cursor -> List a = .fetchall()         # cursor.fetchall()

# `let _ = e` runs a statement for its effect and discards the cursor it returns.
let db = connect ":memory:"
let _ = execute db "create table t (x int)"
let _ = execute db "insert into t values (1), (2), (3)"

# Rows come back as Pyfun tuples; a two-column row is a 2-tuple you destructure.
let firstCol r =
  match r:
    case (x, _): x

let rows = fetchall (execute db "select x, x * x from t order by x")
let total = List.fold (fun acc r -> acc + firstCol r) 0 rows

print rows                                # [(1, 1), (2, 4), (3, 9)]
print total                               # 6
'''),
    "compile_117_471ad8af": ("compile", '''let label s =
  match String.toInt s:
    case Some n: f"number: {n}"
    case None: "no number"

print (label "7")
print (label "nope")
'''),
    "compile_118_0ede5c63": ("compile", '''let mut y = 2
'''),
    "compile_119_11528439": ("compile", '''let clash p =
  let inner = List.fold (fun m (p, l) -> Map.add p l m) Map.empty [(1, 2)]
  (p, Map.toList inner)
let out = clash 9'''),
    "compile_120_1155aed6": ("compile", '''let (a, _) = (1, 2)
'''),
    "compile_121_1652186f": ("compile", '''type Box a = { item: a }
let r = Box { item = 1 } < Box { item = 2 }'''),
    "compile_122_1ec5dbba": ("compile", '''type Point = { x: int, y: int }
let p = Point { x = 1, y = 2 }
let Point { x, y } = p'''),
    "compile_123_1e4f1660": ("compile", '''let rf acc x = match acc: case (m, n): if x == 0 then (Map.empty, n) else (Map.add x x m, n)
let out = match List.fold rf (Map.empty, 0) [0, 1, 2]: case (m, n): (Map.toList m, n)'''),
    "compile_124_1fc8e438": ("compile", '''let step acc x =
  match acc:
    case (m, keep): (Map.add x x m, keep)
let seed = Map.empty
let seed2 = Map.empty
let r = List.fold step (seed, seed2) [1, 2]
let out = match r: case (m, keep): (Map.len m, Map.len keep, Map.len seed2)'''),
    "compile_125_21d2ac54": ("compile", '''let g o = 1 + (match o:
  case Some x if x > 10: 1
  case Some x: 2
  case None: 3)'''),
    "compile_126_32631400": ("compile", '''
        let f n =
          if n == 0 then 0
          else
            let doubled = List.map (fun n -> n + 1) [1, 2]
            f (n - 1)
        '''),
    "compile_127_44267f0e": ("compile", '''let base = 10
let addb acc x = List.concat acc [x + base]
let usefn n =
  let base = 99
  List.fold addb [] [1]
let out = usefn 0'''),
    "compile_128_4e3c7295": ("compile", '''let f xs =
  match xs:
    case [*_, z]: z
    case []: 0'''),
    "compile_129_656acc43": ("compile", '''let k acc x = if List.contains acc [[]] then acc else List.concat acc [x]
let out = List.fold k [] [1, 2, 3]'''),
    "compile_130_73efd7d1": ("compile", '''type P = { x: int, y: int }
let (a, (b, _)) = (1, (2, 3))
let P { x, y } = P { x = 1, y = 2 }'''),
    "compile_131_772ce263": ("compile", '''type C = CH
extern ex: C -> string -> C = .execute()
let g c = ex c'''),
    "compile_132_8d24f3d1": ("compile", '''let w acc x = match acc: case (m, _): (Map.add x x m, Map.empty)
let out = match List.fold w (Map.empty, Map.empty) [1, 2]: case (a, b): (Map.toList a, Map.toList b)'''),
    "compile_133_a3d2620d": ("compile", '''let out = Set.toList (List.fold (fun s (p, _) -> Set.add p s) Set.empty [(1, "a"), (2, "b"), (1, "c")])'''),
    "compile_134_e90c0042": ("compile", '''extern effect : int -> int = builtins.print
let costly xs = List.map ((+) (effect 1)) xs'''),
    "compile_135_f4fc0f5f": ("compile", '''let runWith d s = Decode.decodeString d s
let show r =
  match r:
    case Ok v: f"ok: {v}"
    case Error e: e.errorKind
let out = show (runWith Decode.int "7")
'''),
    "compile_136_f6e59476": ("compile", '''let bump n = n + 100
let dec = Decode.map (fun x -> bump x) Decode.int
let run u =
  let bump = 0
  let r = Decode.decodeString dec "5"
  match r:
    case Ok v: f"ok: {v} ({bump})"
    case Error e: e.errorKind
let useIt = run 0
'''),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_compile_corpus(run, workdir, case):
    """CATCHES: a lowering/emitter that produces different Python for the same program (statement shapes,
    names, imports, helper functions, dataclasses, match vs isinstance ladders, f-string form for the
    3.11 target, annotations in native mode), drops or rewords lowering notes, or compiles a program
    the reference rejects (or the reverse)."""
    mode, source = CASES[case]
    (workdir / "prog.pyfun").write_text(source, encoding="utf-8")
    r = run(ARGS[mode])
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]
