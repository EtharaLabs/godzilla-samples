"""`pyfun check` over a corpus of Pyfun programs harvested from the project's own test-suite and docs.

Each case writes one program to `prog.pyfun`, runs `pyfun check prog.pyfun` and compares the exact
exit code, stdout and stderr (the rustc-style diagnostics: message, `--> line:col`, source excerpt,
caret span, error / hole counts, or `ok: no type errors`) against the reference.
"""

import json

import pytest

from conftest import golden

ARGS = {
    "check": ["check", "prog.pyfun"],
}

# case id -> (mode, program source)
CASES = {
    "check_000_01f85176": ("check", '''let h = List.map ?fn xs'''),
    "check_001_df30447f": ("check", '''import Shapes

type Scene = { name: string, item: Shapes.Placed }

let scene =
  Scene { name = "demo", item = Shapes.Placed { shape = Shapes.Circle 2.0, x = 0.0, y = 0.0 } }

let describe p =
  match p.shape:
    case Shapes.Circle r: f"circle of radius {r}"
    case Shapes.Rect w h: f"{w} by {h} rectangle"

print scene.name
print (describe scene.item)
'''),
    "check_002_8bad799d": ("check", '''let f xs =
  match xs:
    case []: 0
    case [*_, None]: 1'''),
    "check_003_399e3893": ("check", '''let a = M { let x = 1 do! e return! r }
'''),
    "check_004_397cf5fc": ("check", '''def area(w: int, h: int) -> int:
  w * h'''),
    "check_005_5221629b": ("check", '''type A = { x: int }
type B = { y: int }
let b = B { y = 1 }
let oops = b.x'''),
    "check_006_4f6232e7": ("check", '''
        type Placed = { row: int, col: int, letter: string }
        type Cell = { row: int, col: int, letter: string, blank: bool }
        let describe c =
            let l = c.letter
            let flag = c.blank
            f"{l}/{flag}"
        let out = describe (Cell { row = 1, col = 2, letter = "A", blank = false })
        '''),
    "check_007_469538c5": ("check", '''extern flush: unit -> unit = sys.stdout.flush
'''),
    "check_008_f42da8b9": ("check", '''let x = §'''),
    "check_009_b0e66bab": ("check", '''type Placed = { row: int, letter: string }
type Cell = { row: int, letter: string, blank: bool }
let get c = c.letter'''),
    "check_010_0ed99694": ("check", '''measure m
let bad = sqrt 2.0<m^3>'''),
    "check_011_6549880f": ("check", '''let (|Loud|Quiet|) n =
  print n
  if n > 5 then Loud else Quiet
let pure classify n =
  match n:
    case Loud: 1
    case Quiet: 2'''),
    "check_012_67348e46": ("check", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let f o =
  match o:
    case Some Even: 1
    case _: 0'''),
    "check_013_6aae5025": ("check", '''extern send: string -> string ->{io, async} unit = hub.send'''),
    "check_014_6e6b5649": ("check", '''let r = result {
  for x in [1]:
    return x
}'''),
    "check_015_01fb9d1b": ("check", '''type P = { x: bool, y: bool }
let f p =
  match p:
    case P { x = true, y = true }: 1
    case P { x = true, y = false }: 2
    case P { x = false, y = true }: 3'''),
    "check_016_777ff3da": ("check", '''type Spook = S (string ->{spooky} unit)'''),
    "check_017_3ff3a28c": ("check", '''type Option a = None | Some a'''),
    "check_018_11561afb": ("check", '''let (|Blank|_|) s = String.strip s == ""
let f s =
  match s:
    case Blank x: x
    case _: "text"'''),
    "check_019_3c9ffd24": ("check", '''let q = Html { class_ "board" }'''),
    "check_020_4d7db2d2": ("check", '''let f x =
  match x:
    case -1.5: 0
    case _: 1'''),
    "check_021_76ab176b": ("check", '''let xs = [1, 2] + [3]'''),
    "check_022_a1dc1957": ("check", '''let f n =
  match n with
  | 0 -> 1
  | _ -> 2'''),
    "check_023_131c0b02": ("check", '''type P = { x: int, x: int }'''),
    "check_024_7fa8593c": ("check", '''let (|Weird|_|) n = n + 1'''),
    "check_025_f0753f4d": ("check", '''type Point = { x: int }
let z p = p.nope'''),
    "check_026_cb29d9a4": ("check", '''let (Some x) = Some 1
'''),
    "check_027_16a171b1": ("check", '''let a = option { let! x = Some 1 }'''),
    "check_028_2476dc6e": ("check", '''let f ([a, b]) = a'''),
    "check_029_361991e9": ("check", '''type Inner = { a: int, b: int }
type Outer = { inner: Inner, tag: string }
let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }
let o2 = { o with inner = o.inner, inner.a = 1 }'''),
    "check_030_401d6aa3": ("check", '''type Holder = { item: Geometry.Point }'''),
    "check_031_6e07fd2d": ("check", '''type Point = { x: int, y: int }
let p = Point { x = 1 }'''),
    "check_032_24dea788": ("check", '''module Maybe =
  let bind m f =
    match m:
      case Some x: ?
      case None: None
  let return_ x = ?

let addThree a b c =
  Maybe {
    let! x = a
    let! y = b
    let! z = c
    return x + y + z
  }

print (addThree (Some 1) (Some 2) (Some 3))
print (addThree (Some 1) None (Some 3))
'''),
    "check_033_056e07ab": ("check", '''type Color = Red | Green
let (|Red|Other|) n = if n == 0 then Red else Other'''),
    "check_034_324806dd": ("check", '''let f o = Option { let! x = o  return x }'''),
    "check_035_558fd65c": ("check", '''let Pi = 3.14'''),
    "check_036_902b5c82": ("check", '''let a = option { yield 1 }'''),
    "check_037_bc980cc4": ("check", '''let f p =
  match p:
    case (true, b): b'''),
    "check_038_cbcaf21f": ("check", '''let loose = Decode.decodeString Decode.auto "1"'''),
    "check_039_f4454ab7": ("check", '''let double x = return x * 2'''),
    "check_040_766fdbaa": ("check", '''let stray = Task.start (Async.sleep 1.0)
'''),
    "check_041_e2999b02": ("check", '''measure m
measure s

let distance = 240.0<m>
let elapsed = 30.0<s>

# Speed is distance per unit of time. This line does not type-check yet.
let speed = distance + elapsed

print speed
'''),
    "check_042_0ec1b0e2": ("check", '''let f x =
    x + 1
    x'''),
    "check_043_26abf539": ("check", '''type Box a = { item: a }
let mk = Box { item = fun x -> x }
let bad = mk < mk'''),
    "check_044_45a0d905": ("check", '''type Inner = { a: int, b: int }
type Outer = { inner: Inner, tag: string }
let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }
let o2 = { o with inner.a.x = 1 }'''),
    "check_045_759bad3d": ("check", '''type Shape = Circle float | Rect float float
let (|Round|Angular|) s =
  match s:
    case Circle r: Round
    case Rect w h: Angular
let f s =
  match s:
    case Round: 1
    case Angular: 2'''),
    "check_046_98192d4c": ("check", '''measure m
measure s
measure Speed = Accel s
measure Accel = m / s^2'''),
    "check_047_b19d653c": ("check", '''let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)
let f n =
  match n:
    case Small x | Big _: 1'''),
    "check_048_b358aaf8": ("check", '''let (|Even|Odd|) d n = Even'''),
    "check_049_02725cd2": ("check", '''let balance start =
  let acc = start
  acc <- acc + 100
  acc <- acc - 30
  acc <- acc + 50
  acc

print (balance 0)'''),
    "check_050_0caf6f15": ("check", '''let mut f x = x'''),
    "check_051_1f278aa2": ("check", '''## Square root from Python.
extern sqrt: float -> float = math.sqrt
'''),
    "check_052_4e978f0c": ("check", '''let a = seq { return 5 }'''),
    "check_053_5739b6c4": ("check", '''let rec f x = x'''),
    "check_054_5f1967b1": ("check", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let f n =
  match n:
    case Even | 0: 1
    case _: 2'''),
    "check_055_8dbeeebb": ("check", '''extern bad : unit -> a = time.time(tz=...)'''),
    "check_056_ad4d7ca8": ("check", '''let p = Geometry.Point { x = 3, y = 4 }'''),
    "check_057_bce95db8": ("check", '''let mut (a, b) = (1, 2)'''),
    "check_058_f83e0fa8": ("check", '''let (a, b) c = (1, 2)'''),
    "check_059_0841bfcc": ("check", '''nope <- 1'''),
    "check_060_08670abb": ("check", '''let ok = ready || valid'''),
    "check_061_0ec5b600": ("check", '''let mixed n (Cell { letter }) _ = letter'''),
    "check_062_2168b197": ("check", '''module Geom =
  let area w h = w * h
let x = Geom.aera 2 3'''),
    "check_063_3083597d": ("check", '''extern bad : string -> a = .attr(k=...)'''),
    "check_064_6b118afb": ("check", '''opaque type X = int
opaque type X = int'''),
    "check_065_7ab6bb33": ("check", '''extern type Conn
extern use: Conn -> int = m.use
let r = Decode.decodeString Decode.auto "1"
let n = match r:
  case Ok c: use c
  case Error _: 0'''),
    "check_066_010047fd": ("check", '''let m =
  async {
    let! x = m
    )
  }'''),
    "check_067_02a886fc": ("check", '''type Inner = { a: int, b: int }
type Outer = { inner: Inner, tag: string }
let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }
let o2 = { o with inner.z = 1 }'''),
    "check_068_09405f8c": ("check", '''let g k =
  match k:
    case Color.Red: 1
    case Color.Other: 2'''),
    "check_069_0ae1e241": ("check", '''module M =
  let x = 1
let bad = M'''),
    "check_070_29cb8557": ("check", '''let f = Decode.decodeString Decode.auto "1"
let g = match f:
  case Ok h: h 1
  case Error _: 0'''),
    "check_071_3871f829": ("check", '''module List =
  let x = 1'''),
    "check_072_4c75c125": ("check", '''type Point = { x: int, y: int }
let f p =
  match p:
    case Point { x = 0, z = 1 }: 1
    case _: 0'''),
    "check_073_5732a1c8": ("check", '"\\u41"'),
    "check_074_6a249551": ("check", '''let f x =
  let (|A|_|) n = n == 0
  x'''),
    "check_075_6f55d1ba": ("check", '''type Point = { x: int, y: int }
let p = Point { x = 1, y = 2, z = 3 }'''),
    "check_076_c38836ac": ("check", '''module M =
  let x = 1
module M =
  let y = 2'''),
    "check_077_cc2764f3": ("check", '''let a = result { return 1  return 2 }'''),
    "check_078_e04fb841": ("check", '''let (|DivisibleBy|_|) d n = n % d == 0
let f n =
  match n:
    case DivisibleBy "x": "fizz"
    case _: "n"'''),
    "check_079_e14ed4c6": ("check", '''let (|Wrap|) n = if n > 0 then Wrap n else Wrap'''),
    "check_080_e52f4a7d": ("check", '''type Point = { x: int, y: int }
let f p =
  match p:
    case Point { x = 0, x = 1 }: 1
    case _: 0'''),
    "check_081_0e9bed4f": ("check", '''let f xs =
  match xs:
    case []: 0'''),
    "check_082_2419f6a4": ("check", '''
        let a = -5
        let b = abs (-5)
        let c = 2 * -3
        let d = -(4 + 1)
        let sign =
            match -1:
                case -1: "neg"
                case _: "other"
        '''),
    "check_083_b6cea50a": ("check", '''def greet():
  print "hi"'''),
    "check_084_19a7f2dc": ("check", ''':reset
type Point = { x: int, y: int }

let name p =
  match p:
    case Point { x = 0, y = 0 }: "origin"
    case Point { x, y }: "elsewhere"

print (name (Point { x = 0, y = 0 }))
print (name (Point { x = 3, y = 4 }))'''),
    "check_085_6a4c4ef1": ("check", '''let million = 1_000_000
let mask = 0xFF
let bits = 0b1010
let perm = 0o17
let lightSpeed = 3.0e8
let tower = 2.0 ** 3.0 ** 2.0
let q = 17 // 5
let r = 17 % 5
let inRange = 0 <= 7 < 10

print million
print mask
print bits
print perm
print lightSpeed
print tower
print q
print r
print inRange'''),
    "check_086_094c27f0": ("check", '''let x = 3
let a = 4
let b = 5
let m = f"{x=} {a + b = }"
let len = String.len m'''),
    "check_087_0c1cf05c": ("check", '''extern import urllib.'''),
    "check_088_18cea609": ("check", '''let f x =
  def g y = y + 1
  g x'''),
    "check_089_2223498d": ("check", '''let mapped = ((map f) [1, 2, 3])
'''),
    "check_090_294235ae": ("check", '''let (|Positive|_|) n = if n > 0 then Some n else None
let f n =
  match n:
    case Positive: 1
    case _: 0'''),
    "check_091_4615ffaf": ("check", '''let f xs =
  match xs:
    case [*a, *b]: 0'''),
    "check_092_4a8fdda5": ("check", '''f(k=...)'''),
    "check_093_5bbe632a": ("check", '''let ok = ready && valid'''),
    "check_094_d6667c74": ("check", '''extern type Writer
extern type Server
extern closeConn: Writer -> unit = .close()
extern serve: (Writer -> Async unit) -> int -> Async Server = asyncio.start_server
let handle w = async { closeConn w }
let listen = serve handle 7777'''),
    "check_095_eea69506": ("check", '''let f n =
  match n:
    case 0: n
    case _: n
let r = 1.0 + f 0'''),
    "check_096_1c403ee4": ("check", '''let ns = [4, 8, 15, 16, 23]

let total = List.fold ? 0 ns
let atTen = Option.withDefault ? (List.get 10 ns)

print total
print atTen
'''),
    "check_097_45950ee1": ("check", '''let label s =
  match String.toInt s:
    case Some n: f"number: {n}"

print (label "7")
print (label "nope")'''),
    "check_098_991a5849": ("check", '''let describeSign n =
  match n:
    case 0: "zero"
    case m if m > 0: "positive"
'''),
    "check_099_06eec875": ("check", '''type Inner = { a: int, b: int }
type Outer = { inner: Inner, tag: string }
let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }
let o2 = { o with inner.a = 10, tag = "y" }'''),
    "check_100_0f1f8423": ("check", '''let m = Set.max (Set.ofList [1])
let bad = m + 1'''),
    "check_101_1122bd13": ("check", '''match x:'''),
    "check_102_1a995a51": ("check", '''let pure (a, b) =
  print "hi"
  (1, 2)'''),
    "check_103_1ace045b": ("check", '''let s = 1 + "b"'''),
    "check_104_1ace953e": ("check", '''let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs'''),
    "check_105_1cffdcef": ("check", '''let lt = (<)
'''),
    "check_106_1da50501": ("check", '''
        let a = 10 % 3
        let b = 5.5 % 2.0
        let c = -7 % 3
        let d = (%) 17 5
        '''),
    "check_107_298cd4eb": ("check", '''1 2.5 _'''),
    "check_108_2c280935": ("check", '''let one = 1
let bad =
let two = one'''),
    "check_109_2cb72555": ("check", '''let f xs =
  match xs:
    case [x]: x'''),
    "check_110_2e38754e": ("check", '''let ne = (!=)
'''),
    "check_111_3037e0c5": ("check", '''extern get: string ->{async} List string = client.get'''),
    "check_112_36e42b0c": ("check", '''let s = "café → 🎉"'''),
    "check_113_41047e3c": ("check", '''<< <| <='''),
    "check_114_4692b30e": ("check", '''let p = (**)
'''),
    "check_115_4dc98679": ("check", '''import geometry'''),
    "check_116_4e11d5e3": ("check", '''let f n =
  result {
    let! x =
      Option.toResult "bad"
        (String.toInt n)
    let y = x
      |> (fun v -> v * 2)
    let z =
      match y:
        case 0: 0
        case other: other
    let! w = result { return z }
    return w
  }'''),
    "check_117_50efcdbb": ("check", '''let f x =
  match x:
    case 1.5: 0
    case _: 1'''),
    "check_118_551c1525": ("check", '''let f (a | b) = a'''),
    "check_119_58d4e75f": ("check", '''|> |'''),
    "check_120_5bde15bf": ("check", '''. . .'''),
    "check_121_5c070526": ("check", '''let f (0) = 1'''),
    "check_122_5baea692": ("check", 'let p = "C:\\\\path\\nnext"\n'),
    "check_123_5e5b740b": ("check", '''"""'''),
    "check_124_7a11cfb3": ("check", '''extern type Pair a b'''),
    "check_125_7b2c4717": ("check", '''extern bad: (a ->{E} unit) -> unit = mymod.bad'''),
    "check_126_85786098": ("check", '''let r = (//) 7 2'''),
    "check_127_8965d6df": ("check", '''let f xs =
  match xs:
    case []: 0
    case [x]: x
    case [x, y]: y
    case [a, *rest]: a'''),
    "check_128_8be37285": ("check", '''let a = 1
## dangling note'''),
    "check_129_8d1acf02": ("check", '''let _ a = a'''),
    "check_130_8f01b061": ("check", '"\\z"'),
    "check_131_95333152": ("check", '''
        type Tree = Leaf int | Node Tree Tree
        let ordered = List.sort [Node (Leaf 2) (Leaf 3), Leaf 5, Leaf 1]
        '''),
    "check_132_9964cc15": ("check", '''module Maybe =
  let bind m f =
    match m:
      case Some x: f x
      case None: None
  let return_ x = Some x
  let returnFrom m = m
let r =
  Maybe {
    return 1
    return 2
  }'''),
    "check_133_9c059151": ("check", '''let r = String.UPPER "x"'''),
    "check_134_9c1cd8a7": ("check", '''opaque type X = Nope'''),
    "check_135_a69b6978": ("check", '''let f x =
  x +
let g = 2'''),
    "check_136_a8198df7": ("check", '''## Splits parity.
let (|Even|Odd|) n = (if ((n % 2) == 0) then Even else Odd)
'''),
    "check_137_b66126e3": ("check", '''let f (p as q) = q'''),
    "check_138_ba09bd3c": ("check", '''let line = "-" * 20'''),
    "check_139_bd48e34f": ("check", '''let s = seq { for x in 3: yield x }'''),
    "check_140_bf6a07b6": ("check", '''measure m
measure s
let bad = min 3<m> 5<s>'''),
    "check_141_c044fca5": ("check", '''...'''),
    "check_142_d907ea29": ("check", '''measure m
let sq x = x * x
let f x = sq x == 5.0<m^3>'''),
    "check_143_e316d4f8": ("check", '''let mut _ = 1'''),
    "check_144_f6bd8538": ("check", '''let f =
  result {
    let! x = g (h
i)
    return x
  }'''),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_check_corpus(run, workdir, case):
    """CATCHES: a type checker that accepts an ill-typed program or rejects a valid one, reports a different
    message, location, caret span or error count, orders multiple diagnostics differently, misses an
    exhaustiveness/effect/unit/mutability rule, or exits with the wrong status."""
    mode, source = CASES[case]
    (workdir / "prog.pyfun").write_text(source, encoding="utf-8")
    r = run(ARGS[mode])
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]
