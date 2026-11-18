"""IFC import: hand-written IFC2x3 and IFC4 files read into a project, element by element, with what is left out and why.

Each file is written in the test with a small STEP writer (`Ifc`). What the import made is read back through the CLI:
`run x.ifc --cmd 'elements {}'` (the open reply, then every element) and, where types, materials, families, parameters or
phases matter, `inspect`, less what a new project already holds.
"""

import json

import pytest
from conftest import make_project, normalize

MM = "IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)"


def f(x):
    """A STEP real."""
    return repr(float(x))


class Ifc:
    """An IFC file written entity by entity: `add` writes `#n=ENTITY;` and returns `#n`. Lengths are given in mm and
    written in the file's unit (`unit_mm` millimetres to one)."""

    def __init__(self, schema="IFC4", name="Test", units=(MM,), unit_mm=1.0, header=None):
        self.rows, self.n, self.unit_mm, self.schema = [], 0, unit_mm, schema
        self.header = header
        self.contained = {}
        made = [self.add(u) for u in units]
        assignment = self.add(f"IFCUNITASSIGNMENT(({','.join(made)}))")
        self.project = self.add(f"IFCPROJECT('p',$,{name},$,$,$,$,$,{assignment})")
        self.origin = self.add("IFCCARTESIANPOINT((0.,0.,0.))")
        self.world = self.add(f"IFCAXIS2PLACEMENT3D({self.origin},$,$)")
        self.site = self.add(f"IFCLOCALPLACEMENT($,{self.world})")
        self.up = self.add("IFCDIRECTION((0.,0.,1.))")

    def add(self, entity):
        self.n += 1
        self.rows.append(f"#{self.n}={entity};")
        return f"#{self.n}"

    def fixed(self, n, entity):
        """`#n=ENTITY;` at a number of its own, for what is named before it is written (a unit's parts)."""
        self.rows.append(f"#{n}={entity};")
        return f"#{n}"

    def mm(self, x):
        return f(x / self.unit_mm)

    def pt(self, *c):
        return self.add(f"IFCCARTESIANPOINT(({','.join(self.mm(x) for x in c)}))")

    def dir(self, *c):
        return self.add(f"IFCDIRECTION(({','.join(f(x) for x in c)}))")

    def axes(self, at=(0, 0, 0), z=None, x=None):
        z = self.dir(*z) if z else "$"
        x = self.dir(*x) if x else "$"
        return self.add(f"IFCAXIS2PLACEMENT3D({self.pt(*at)},{z},{x})")

    def place(self, at=(0, 0, 0), rel=None, z=None, x=None):
        return self.add(f"IFCLOCALPLACEMENT({rel or self.site},{self.axes(at, z, x)})")

    def storey(self, name="'Level 0'", elevation=0.0):
        at = self.place((0, 0, elevation))
        s = self.add(f"IFCBUILDINGSTOREY('s{self.n}',$,{name},$,$,{at},$,$,.ELEMENT.,{self.mm(elevation)})")
        self.contained.setdefault(s, [])
        return s, at

    def polyline(self, pts, closed=False):
        refs = [self.pt(*p) for p in pts]
        if closed:
            refs.append(refs[0])
        return self.add(f"IFCPOLYLINE(({','.join(refs)}))")

    def ring(self, pts):
        """An arbitrary closed profile through `pts`."""
        return self.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{self.polyline(pts, True)})")

    def rect(self, w, h, centre=None):
        at = "$"
        if centre is not None:
            at = self.add(f"IFCAXIS2PLACEMENT2D({self.pt(*centre)},$)")
        return self.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,{at},{self.mm(w)},{self.mm(h)})")

    def extrude(self, profile, depth, at=None, direction=None, z=None, xdir=None):
        """`profile` swept `depth` along `direction` (up, unless told) of its position: at `at`, its own z along `z`."""
        pos = self.axes(at or (0, 0, 0), z, xdir) if at is not None or z is not None else "$"
        d = self.dir(*direction) if direction else self.up
        return self.add(f"IFCEXTRUDEDAREASOLID({profile},{pos},{d},{self.mm(depth)})")

    def shape(self, *items, ident="Body", kind="SweptSolid", axis=None):
        reps = [self.add(f"IFCSHAPEREPRESENTATION($,'{ident}','{kind}',({','.join(items)}))")]
        if axis is not None:
            reps.append(self.add(f"IFCSHAPEREPRESENTATION($,'Axis','Curve2D',({axis}))"))
        return self.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({','.join(reps)}))")

    def brep(self, faces):
        """A faceted Brep of `faces`, each a list of points turned out."""
        made = []
        for face in faces:
            loop = self.add(f"IFCPOLYLOOP(({','.join(self.pt(*p) for p in face)}))")
            bound = self.add(f"IFCFACEOUTERBOUND({loop},.T.)")
            made.append(self.add(f"IFCFACE(({bound}))"))
        shell = self.add(f"IFCCLOSEDSHELL(({','.join(made)}))")
        return self.add(f"IFCFACETEDBREP({shell})")

    def product(self, entity, storey=None):
        """`entity` (its text, with `#` for nothing yet) in `storey`'s spatial structure."""
        ref = self.add(entity)
        if storey is not None:
            self.contained.setdefault(storey, []).append(ref)
        return ref

    def text(self):
        rows = list(self.rows)
        for k, (storey, products) in enumerate(self.contained.items()):
            if products:
                rows.append(f"#{900000 + k}=IFCRELCONTAINEDINSPATIALSTRUCTURE('c{k}',$,$,$,({','.join(products)}),{storey});")
        header = self.header or f"FILE_DESCRIPTION((''),'2;1');\nFILE_NAME('x.ifc','',(''),(''),'','','');\nFILE_SCHEMA(('{self.schema}'));"
        return "ISO-10303-21;\nHEADER;\n" + header + "\nENDSEC;\nDATA;\n" + "\n".join(rows) + "\nENDSEC;\nEND-ISO-10303-21;\n"


def box(x0, y0, z0, x1, y1, z1):
    """A box's six faces, turned out."""
    a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
    lo = [(p[0], p[1], z0) for p in (a, d, c, b)]
    hi = [(p[0], p[1], z1) for p in (a, b, c, d)]
    sides = [[(p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)] for p, q in ((a, b), (b, c), (c, d), (d, a))]
    return [lo, hi, *sides]


# ---------------------------------------------------------------------------------------------------------------------
# Reading what came in.

def _inspect(run, args):
    r = run(args)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode().splitlines()[-1])


def _bare(v):
    """`v` less the ids and GUIDs in it, which a new project's library entries get afresh."""
    if isinstance(v, dict):
        return {k: _bare(x) for k, x in v.items() if k not in ("id", "guid")}
    return [_bare(x) for x in v] if isinstance(v, list) else v


def _delta(now, before):
    """What `now` holds that `before` doesn't, or holds otherwise (ids and GUIDs aside): objects compared key by key,
    anything else whole."""
    out = {}
    for k, v in now.items():
        was = before.get(k, None)
        if isinstance(v, dict) and isinstance(was, dict):
            d = _delta(v, was)
            out.update({k: d} if d else {})
        else:
            out.update({} if _bare(v) == _bare(was) and k in before else {k: v})
    return out


def imported(run, workdir, text, *cmds, inspect=True, name="x.ifc"):
    """The file `text` saved as `name`, opened with `run`, every element listed and the commands `cmds` run; then, with
    `inspect`, what the project holds beyond a new project's (its types, materials, families, parameters, phases…)."""
    (workdir / name).write_text(text, encoding="utf-8")
    args = ["run", name, "--cmd", "elements {}"]
    for c in cmds:
        args += ["--cmd", c]
    r = run(args)
    out = f"exit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}"
    if inspect and r.returncode == 0:
        now = _inspect(run, ["run", name, "--cmd", "inspect"])
        new = _inspect(run, ["run", "--cmd", "inspect"])
        extra = "--- inspect, less a new project's\n" + json.dumps(_delta(now, new), indent=1, sort_keys=True) + "\n"
    else:
        extra = ""
    return normalize(out + extra)


# ---------------------------------------------------------------------------------------------------------------------
# The STEP file itself.

HEAD = "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n"

BROKEN = {
    "no_header": "ISO-10303-21;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n",
    "header_entry_without_parameters": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA;\nENDSEC;\n",
    "header_never_ends": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\n",
    "no_data_section": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\nENDSEC;\n#1=IFCWALL();\n",
    "data_without_semicolon": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA\n#1=IFCWALL();\n",
    "string_never_ends": HEAD + "#1=IFCPROJECT('x',$,'unterminated);\nENDSEC;\n",
    "list_never_closes": HEAD + "#1=IFCX(1,2\n",
    "deep_open_parentheses": HEAD + "#1=IFCWALL('x',$,(((((;\n",
    "entity_number_too_big": HEAD + "#99999999999999999999999=IFCX();\nENDSEC;\n",
    "entity_without_number": HEAD + "#=IFCX();\nENDSEC;\n",
    "entity_without_hash": HEAD + "1=IFCX();\nENDSEC;\n",
    "entity_without_equals": HEAD + "#1 IFCX();\nENDSEC;\n",
    "entity_without_name": HEAD + "#1=123;\nENDSEC;\n",
    "entity_without_semicolon": HEAD + "#1=IFCX()\n#2=IFCY();\nENDSEC;\n",
    "enum_never_closes": HEAD + "#1=IFCX(.T);\nENDSEC;\n",
    "binary_never_closes": HEAD + '#1=IFCX("0FF);\nENDSEC;\n',
    "number_with_two_points": HEAD + "\n\n#1=IFCX(1.2.3);\nENDSEC;\n",
    "unexpected_character": HEAD + "#1=IFCX(@);\nENDSEC;\n",
    "nested_too_deep": HEAD + "#1=IFCX(" + "(" * 40 + "1" + ")" * 40 + ");\nENDSEC;\n",
    "comment_never_closes": HEAD + "#1=IFCX(); /* a note that never ends\nENDSEC;\n",
    "data_never_ends": HEAD + "#1=IFCX();\n",
    "not_ifc": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n",
    "no_schema": "ISO-10303-21;\nHEADER;\nFILE_NAME('x');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n",
    "no_project": HEAD + "#1=IFCWALL('w',$,'Wall',$,$,$,$,$,$);\nENDSEC;\nEND-ISO-10303-21;\n",
    "length_unit_of_nothing": HEAD + "#1=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(0.),#2);\n#2=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n"
    "#3=IFCCONVERSIONBASEDUNIT(#4,.LENGTHUNIT.,'nothing',#1);\n#4=IFCDIMENSIONALEXPONENTS(1,0,0,0,0,0,0);\n"
    "#5=IFCUNITASSIGNMENT((#3));\n#6=IFCPROJECT('p',$,'P',$,$,$,$,$,#5);\nENDSEC;\nEND-ISO-10303-21;\n",
    "length_unit_of_light_years": HEAD + "#1=IFCSIUNIT(*,.LENGTHUNIT.,.EXA.,.METRE.);\n"
    "#5=IFCUNITASSIGNMENT((#1));\n#6=IFCPROJECT('p',$,'P',$,$,$,$,$,#5);\nENDSEC;\nEND-ISO-10303-21;\n",
    "negative_angle_unit": HEAD + "#1=IFCMEASUREWITHUNIT(IFCPLANEANGLEMEASURE(-1.),#2);\n#2=IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);\n"
    "#3=IFCCONVERSIONBASEDUNIT(#4,.PLANEANGLEUNIT.,'backwards',#1);\n#4=IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0);\n"
    "#5=IFCUNITASSIGNMENT((#3));\n#6=IFCPROJECT('p',$,'P',$,$,$,$,$,#5);\nENDSEC;\nEND-ISO-10303-21;\n",
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_a_broken_ifc_file_is_refused_with_what_is_wrong_and_where(run, workdir, golden, case):
    """CATCHES: a rewrite whose STEP reader accepts a damaged file, crashes on it, or words the error differently: which
    line, what was expected there, a schema that isn't IFC, a file with no IfcProject, a length or angle unit out of range."""
    (workdir / "bad.ifc").write_text(BROKEN[case])
    golden.check_run(run(["info", "bad.ifc"]), f"broken_{case}.txt")


def test_strings_escapes_comments_and_odd_values_read_as_the_standard_says(run, workdir, golden):
    """CATCHES: a rewrite that mis-decodes STEP strings (`''`, `\\\\`, `\\X2\\…\\X0\\`, `\\X4\\…\\X0\\`, `\\X\\hh`, `\\S\\`,
    a code page switch), trips over comments, a named DATA section, a complex instance or `*`, or names storeys differently
    (a long name for a missing name, `Level` for none, `(2)` for a repeat, an elevation from the attribute without a
    placement, lowest first)."""
    header = "FILE_DESCRIPTION(('a;b'),'2;1'); /* a note; with ) */\nFILE_NAME('x.ifc','',(''),(''),'','','');\nFILE_SCHEMA(($,'ifc4'));"
    x = Ifc(name=r"'It''s \X2\00D6\X0\ffice \X4\0001F600\X0\ caf\X\E9 \S\D \PA\x a\\b \Q'", header=header)
    x.rows[0] = "/* metres? no: millimetres */ " + x.rows[0]
    x.add("(IFCREPRESENTATIONITEM()IFCGEOMETRICREPRESENTATIONITEM())")
    x.add(f"IFCBUILDINGSTOREY('a',*,$,$,'Upper long name',$,$,'Upper long name',.element.,{x.mm(6000)})")
    x.add(f"IFCBUILDINGSTOREY('b',$,$,$,$,{x.place((0, 0, 3000))},$,$,.ELEMENT.,$)")
    x.add(f"IFCBUILDINGSTOREY('c',$,'Twin',$,$,$,$,$,.ELEMENT.,{x.mm(-1500)})")
    x.add(f"IFCBUILDINGSTOREY('d',$,'Twin',$,$,$,$,$,.ELEMENT.,{x.mm(9000.25)})")
    x.add("IFCPROPERTYSINGLEVALUE('Binary',$,IFCBINARY(\"0FF\"),$)")
    text = x.text().replace("DATA;\n", "DATA('section', ('IFC4'));\n", 1)
    golden.check(imported(run, workdir, text, inspect=False), "step_strings.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Files harvested from other tools' ways of writing.

def meshes(site="0.,0.,0."):
    """An IFC4 file in mm whose wall is a triangle mesh with no axis, running north, and whose column takes its shape from
    its type through a mapped item; `site` places it all."""
    pts = "(0.,-100.,0.),(5000.,-100.,0.),(5000.,100.,0.),(0.,100.,0.),(0.,-100.,2700.),(5000.,-100.,2700.),(5000.,100.,2700.),(0.,100.,2700.)"
    tris = "(1,3,2),(1,4,3),(5,6,7),(5,7,8),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,4,8),(3,8,7),(4,1,5),(4,5,8)"
    return f"""ISO-10303-21;HEADER;FILE_SCHEMA(('IFC4'));ENDSEC;DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCPROJECT('p',$,'Meshes',$,$,$,$,$,#2);
#4=IFCCARTESIANPOINT((0.,0.,0.));
#5=IFCAXIS2PLACEMENT3D(#4,$,$);
#6=IFCLOCALPLACEMENT(#62,#5);
#7=IFCBUILDINGSTOREY('s',$,'Level 0',$,$,#6,$,$,.ELEMENT.,0.);
#10=IFCCARTESIANPOINTLIST3D(({pts}));
#11=IFCTRIANGULATEDFACESET(#10,$,.T.,({tris}),$);
#12=IFCSHAPEREPRESENTATION($,'Body','Tessellation',(#11));
#13=IFCPRODUCTDEFINITIONSHAPE($,$,(#12));
#14=IFCCARTESIANPOINT((1000.,2000.,0.));
#15=IFCDIRECTION((0.,1.,0.));
#16=IFCDIRECTION((0.,0.,1.));
#17=IFCAXIS2PLACEMENT3D(#14,#16,#15);
#18=IFCLOCALPLACEMENT(#6,#17);
#19=IFCWALL('w',$,'Wall',$,$,#18,#13,$,$);
#30=IFCRECTANGLEPROFILEDEF(.AREA.,$,$,300.,500.);
#31=IFCEXTRUDEDAREASOLID(#30,$,#16,3000.);
#32=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#31));
#33=IFCREPRESENTATIONMAP(#5,#32);
#34=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#4,$,$);
#35=IFCMAPPEDITEM(#33,#34);
#36=IFCSHAPEREPRESENTATION($,'Body','MappedRepresentation',(#35));
#37=IFCPRODUCTDEFINITIONSHAPE($,$,(#36));
#38=IFCCARTESIANPOINT((3000.,4000.,0.));
#39=IFCAXIS2PLACEMENT3D(#38,#16,$);
#40=IFCLOCALPLACEMENT(#6,#39);
#41=IFCCOLUMN('c',$,'Column',$,$,#40,#37,$,$);
#50=IFCRELCONTAINEDINSPATIALSTRUCTURE('r',$,$,$,(#19,#41),#7);
#60=IFCCARTESIANPOINT(({site}));
#61=IFCAXIS2PLACEMENT3D(#60,$,$);
#62=IFCLOCALPLACEMENT($,#61);
ENDSEC;END-ISO-10303-21;"""


@pytest.mark.parametrize("site", ["0.,0.,0.", "500000000.,5000000000.,0."])
def test_a_mesh_wall_and_a_mapped_column(run, workdir, golden, site):
    """CATCHES: a rewrite that can't measure a wall from a triangle mesh without an axis, or a column whose body is its
    type's mapped representation; or that doesn't bring a model at map coordinates near the origin and say how far
    (`moved`), keeping it where it is otherwise."""
    golden.check(imported(run, workdir, meshes(site)), f"meshes_{site.split('.')[0]}.txt")


OFFICE = r"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');
FILE_NAME('office.ifc','2026-10-15T10:00:00',(''),(''),'hand','hand','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
/* metres */
#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCCARTESIANPOINT((0.,0.,0.));
#4=IFCAXIS2PLACEMENT3D(#3,$,$);
#5=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#4,$);
#6=IFCPROJECT('0000000000000000000001',$,'Small \X2\00D6\X0\ffice',$,$,$,$,(#5),#2);
#10=IFCLOCALPLACEMENT($,#4);
#11=IFCSITE('0000000000000000000002',$,'Site',$,$,#10,$,$,.ELEMENT.,$,$,$,$,$);
#12=IFCLOCALPLACEMENT(#10,#4);
#13=IFCBUILDING('0000000000000000000003',$,'Building',$,$,#12,$,$,.ELEMENT.,$,$,$);
#20=IFCLOCALPLACEMENT(#12,#4);
#21=IFCBUILDINGSTOREY('0000000000000000000004',$,'Ground',$,$,#20,$,$,.ELEMENT.,0.);
#22=IFCCARTESIANPOINT((0.,0.,3.));
#23=IFCAXIS2PLACEMENT3D(#22,$,$);
#24=IFCLOCALPLACEMENT(#12,#23);
#25=IFCBUILDINGSTOREY('0000000000000000000005',$,'First',$,$,#24,$,$,.ELEMENT.,3.);
#30=IFCCARTESIANPOINT((1.,2.,0.));
#31=IFCDIRECTION((0.,0.,1.));
#32=IFCDIRECTION((0.,1.,0.));
#33=IFCAXIS2PLACEMENT3D(#30,#31,#32);
#34=IFCLOCALPLACEMENT(#24,#33);
#35=IFCCARTESIANPOINT((0.,0.));
#36=IFCCARTESIANPOINT((5.,0.));
#37=IFCPOLYLINE((#35,#36));
#38=IFCSHAPEREPRESENTATION(#5,'Axis','Curve2D',(#37));
#39=IFCCARTESIANPOINT((0.,0.2));
#40=IFCCARTESIANPOINT((5.,0.2));
#41=IFCPOLYLINE((#35,#36,#40,#39,#35));
#42=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#41);
#43=IFCEXTRUDEDAREASOLID(#42,#4,#31,2.7);
#44=IFCSHAPEREPRESENTATION(#5,'Body','SweptSolid',(#43));
#45=IFCPRODUCTDEFINITIONSHAPE($,$,(#38,#44));
#46=IFCWALLSTANDARDCASE('0000000000000000000006',$,'Basic Wall:Exterior:101',$,'Basic Wall:Exterior',#34,#45,'101');
#50=IFCCARTESIANPOINT((5.,4.,0.));
#51=IFCDIRECTION((-1.,0.,0.));
#52=IFCAXIS2PLACEMENT3D(#50,#31,#51);
#53=IFCLOCALPLACEMENT(#24,#52);
#54=IFCCARTESIANPOINT((2.,0.));
#55=IFCAXIS2PLACEMENT2D(#54,$);
#56=IFCRECTANGLEPROFILEDEF(.AREA.,$,#55,4.,0.1);
#57=IFCEXTRUDEDAREASOLID(#56,#4,#31,2.7);
#58=IFCSHAPEREPRESENTATION(#5,'Body','SweptSolid',(#57));
#59=IFCPRODUCTDEFINITIONSHAPE($,$,(#58));
#60=IFCWALL('0000000000000000000007',$,'Partition',$,$,#53,#59,$);
#70=IFCCARTESIANPOINT((3.,0.3,0.9));
#71=IFCDIRECTION((0.,-1.,0.));
#72=IFCDIRECTION((1.,0.,0.));
#73=IFCAXIS2PLACEMENT3D(#70,#71,#72);
#74=IFCLOCALPLACEMENT(#34,#4);
#75=IFCCARTESIANPOINT((0.5,0.6));
#76=IFCAXIS2PLACEMENT2D(#75,$);
#77=IFCRECTANGLEPROFILEDEF(.AREA.,$,#76,1.,1.2);
#78=IFCEXTRUDEDAREASOLID(#77,#73,#31,0.4);
#79=IFCSHAPEREPRESENTATION(#5,'Body','SweptSolid',(#78));
#80=IFCPRODUCTDEFINITIONSHAPE($,$,(#79));
#81=IFCOPENINGELEMENT('0000000000000000000008',$,'Opening',$,$,#74,#80,$);
#82=IFCRELVOIDSELEMENT('0000000000000000000009',$,$,$,#46,#81);
#83=IFCLOCALPLACEMENT(#74,#4);
#84=IFCWINDOW('000000000000000000000A',$,'Fixed:1000 x 1200:201',$,'Fixed:1000 x 1200',#83,$,'201',1.2,1.);
#85=IFCRELFILLSELEMENT('000000000000000000000B',$,$,$,#81,#84);
#90=IFCCARTESIANPOINT((1.,2.));
#91=IFCCARTESIANPOINT((5.,2.));
#92=IFCCARTESIANPOINT((5.,3.9));
#93=IFCCARTESIANPOINT((1.,3.9));
#94=IFCPOLYLINE((#90,#91,#92,#93,#90));
#95=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#94);
#96=IFCEXTRUDEDAREASOLID(#95,#4,#31,2.5);
#97=IFCSHAPEREPRESENTATION(#5,'Body','SweptSolid',(#96));
#98=IFCPRODUCTDEFINITIONSHAPE($,$,(#97));
#99=IFCLOCALPLACEMENT(#24,#4);
#100=IFCSPACE('000000000000000000000C',$,'101',$,$,#99,#98,'Office',.ELEMENT.,.INTERNAL.,$);
#101=IFCRELAGGREGATES('000000000000000000000D',$,$,$,#25,(#100));
#110=IFCCARTESIANPOINT((0.,0.,-0.25));
#111=IFCAXIS2PLACEMENT3D(#110,$,$);
#112=IFCCARTESIANPOINT((0.8,1.9));
#113=IFCCARTESIANPOINT((5.2,1.9));
#114=IFCCARTESIANPOINT((5.2,4.1));
#115=IFCCARTESIANPOINT((2.,4.1));
#116=IFCCARTESIANPOINT((2.,7.1));
#117=IFCCARTESIANPOINT((0.8,7.1));
#118=IFCPOLYLINE((#112,#113,#114,#115,#116,#117,#112));
#119=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#118);
#120=IFCEXTRUDEDAREASOLID(#119,#111,#31,0.25);
#121=IFCSHAPEREPRESENTATION(#5,'Body','SweptSolid',(#120));
#122=IFCPRODUCTDEFINITIONSHAPE($,$,(#121));
#123=IFCLOCALPLACEMENT(#24,#4);
#124=IFCSLAB('000000000000000000000E',$,'Floor:Generic 250mm',$,'Floor:Generic 250mm',#123,#122,$,.FLOOR.);
#130=IFCCARTESIANPOINT((0.,-1.));
#131=IFCCARTESIANPOINT((0.,8.));
#132=IFCPOLYLINE((#130,#131));
#133=IFCGRIDAXIS('1',#132,.T.);
#134=IFCCARTESIANPOINT((-1.,0.));
#135=IFCCARTESIANPOINT((6.,0.));
#136=IFCPOLYLINE((#134,#135));
#137=IFCGRIDAXIS('A',#136,.T.);
#138=IFCLOCALPLACEMENT(#12,#4);
#139=IFCGRID('000000000000000000000F',$,'Grid',$,$,#138,$,(#133),(#137),$);
#140=IFCFURNISHINGELEMENT('000000000000000000000G',$,'Desk',$,$,#99,$,$);
#150=IFCRELCONTAINEDINSPATIALSTRUCTURE('000000000000000000000H',$,$,$,(#46,#60,#84,#124,#140),#25);
#151=IFCRELCONTAINEDINSPATIALSTRUCTURE('000000000000000000000I',$,$,$,(#139),#21);
#152=IFCRELAGGREGATES('000000000000000000000J',$,$,$,#13,(#21,#25));
ENDSEC;
END-ISO-10303-21;
"""


def test_an_ifc2x3_office_in_metres(run, workdir, golden):
    """CATCHES: a rewrite that reads IFC2x3 in metres wrongly: a wall drawn on its face with an axis (its centre line 100 mm
    in), a partition with no axis carried on to the wall's centre line, a window in an opening cut sideways through the
    wall (its sill and its place along the wall), an L-shaped slab, a room by its number and long name, grids, a desk
    with no body left out, a Revit tag that is only an id not taken as a mark; or that finds an element by a GlobalId
    that names no GUID an element may have (these files' are small numbers)."""
    golden.check(imported(run, workdir, OFFICE, 'select_by_id {"text": "0000000000000000000006 000000000000000000000E nothing"}'),
                 "office.txt")


def test_a_damaged_office_still_reads_or_fails_cleanly(run, workdir, golden):
    """CATCHES: a rewrite that hangs or crashes on placements that point at each other in a ring, instead of reading what
    it can (each chain is walked only so deep)."""
    cycle = OFFICE.replace("#24=IFCLOCALPLACEMENT(#12,#23);", "#24=IFCLOCALPLACEMENT(#34,#23);")
    golden.check(imported(run, workdir, cycle, inspect=False), "office_cycle.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Walls.

def walls_file():
    """Walls written every way a file may: an axis and a profile, no axis on a turned placement, a near miss of a T, a
    clipped body, a union, a tapered extrusion of a repeated label, a Brep with a type, a surface model of bounds turned
    back, a polygonal face set through its point index, no body, and a body with no thickness."""
    x = Ifc(name="'Walls'")
    s0, at0 = x.storey("'Ground'", 0)
    s1, at1 = x.storey("'Upper'", 3000)
    x.storey("'Roof'", 6000)
    south = x.shape(x.extrude(x.rect(6000, 200, (3000, 0)), 3000), axis=x.polyline([(0, 0), (6000, 0)]))
    x.product(f"IFCWALLSTANDARDCASE('2O2Fr$t4X7Zf8NOew3FLOH',$,'South',$,$,{x.place(rel=at0)},{south},$,.STANDARD.)", s0)
    east = x.shape(x.extrude(x.rect(4000, 200, (2000, 0)), 3000))
    x.product(f"IFCWALL('1kTvXnbbzCWw8lcMd1dR4o',$,'East',$,'Basic Wall:Generic 200',{x.place((6000, 0, 0), at0, x=(0, 1, 0))},{east},$,$)", s0)
    tee = x.shape(x.extrude(x.rect(3850, 100, (1925, 0)), 3000), axis=x.polyline([(0, 0), (3850, 0)]))
    x.product(f"IFCWALL('w3',$,'Partition',$,$,{x.place((3000, 150, 0), at0, x=(0, 1, 0))},{tee},$,$)", s0)
    half = x.add(f"IFCHALFSPACESOLID(IFCPLANE({x.axes((0, 0, 2500))}),.F.)")
    clipped = x.add(f"IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,{x.extrude(x.rect(6000, 200, (3000, 4000)), 3000)},{half})")
    x.product(f"IFCWALL('w4',$,'North',$,$,{x.place(rel=at0)},{x.shape(clipped, kind='Clipping')},$,$)", s0)
    a, b = x.extrude(x.rect(3000, 200, (1500, 8000)), 3000), x.extrude(x.rect(3000, 200, (4500, 8000)), 3000)
    union = x.add(f"IFCBOOLEANRESULT(.UNION.,{a},{b})")
    x.product(f"IFCWALL('w5',$,'Upstairs',$,$,{x.place(rel=at1)},{x.shape(union, kind='CSG')},$,$)", s1)
    tapered = x.add(f"IFCEXTRUDEDAREASOLIDTAPERED({x.rect(3000, 150, (1500, -3000))},$,{x.up},{x.mm(2800)},{x.rect(3000, 150, (1500, -3000))})")
    x.product(f"IFCWALL('w6',$,'Garden',$,'Basic Wall:Generic 200',{x.place(rel=at0)},{x.shape(tapered)},$,$)", s0)
    brick = x.product(f"IFCWALLELEMENTEDCASE('w7',$,'West',$,$,{x.place((-4000, 0, 0), at0, x=(0, 1, 0))},"
                      f"{x.shape(x.brep(box(0, -125, 0, 4000, 125, 2800)), kind='Brep')},$,$)", s0)
    kind = x.add("IFCWALLTYPE('t1',$,'Brick 250',$,$,$,$,$,$,.STANDARD.)")
    x.add(f"IFCRELDEFINESBYTYPE('r1',$,$,$,({brick}),{kind})")
    faces = []
    for face in box(0, -100, 0, 4000, 100, 2700):
        loop = x.add(f"IFCPOLYLOOP(({','.join(x.pt(*p) for p in reversed(face))}))")
        faces.append(x.add(f"IFCFACESURFACE(({x.add(f'IFCFACEBOUND({loop},.F.)')}),$,.T.)"))
    shell = x.add(f"IFCSHELLBASEDSURFACEMODEL(({x.add(f'IFCOPENSHELL(({chr(44).join(faces)}))')}))")
    x.product(f"IFCWALL('w8',$,'Shell',$,$,{x.place((-8000, 0, 0), at0, x=(0, 1, 0))},{x.shape(shell, kind='SurfaceModel')},$,$)", s0)
    corners = [(0, -150, 0), (4000, -150, 0), (4000, 150, 0), (0, 150, 0), (0, -150, 2700), (4000, -150, 2700), (4000, 150, 2700), (0, 150, 2700)]
    coords = x.add(f"IFCCARTESIANPOINTLIST3D(({','.join('(' + ','.join(x.mm(c) for c in p) + ')' for p in corners)}))")
    # Each face names its corners through the point index, which lists them backwards.
    quads = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    polys = [x.add(f"IFCINDEXEDPOLYGONALFACE(({','.join(str(9 - k) for k in q)}))") for q in quads]
    faceset = x.add(f"IFCPOLYGONALFACESET({coords},.T.,({','.join(polys)}),(8,7,6,5,4,3,2,1))")
    x.product(f"IFCWALL('w9',$,'Mesh',$,$,{x.place((-12000, 0, 0), at0, x=(0, 1, 0))},{x.shape(faceset, ident='Facetation', kind='Tessellation')},$,$)", s0)
    x.product(f"IFCWALL('w10',$,'Ghost',$,$,{x.place(rel=at0)},$,$,$)", s0)
    flat = [(0, 0, 0), (3000, 0, 0), (3000, 0, 2700), (0, 0, 2700)]
    loop = x.add(f"IFCPOLYLOOP(({','.join(x.pt(*p) for p in flat)}))")
    face = x.add(f"IFCFACE(({x.add(f'IFCFACEOUTERBOUND({loop},.T.)')}))")
    surface = x.add(f"IFCFACEBASEDSURFACEMODEL(({x.add(f'IFCCONNECTEDFACESET(({face}))')}))")
    x.product(f"IFCWALL('w11',$,'Sheet',$,$,{x.place((0, -9000, 0), at0)},{x.shape(surface, ident='Surface2', kind='SurfaceModel')},$,$)", s0)
    return x.text()


def test_walls_measured_from_every_kind_of_body(run, workdir, golden):
    """CATCHES: a rewrite that measures a wall's line, thickness, height, level and top level wrongly from an axis, a
    turned placement, a clipped or united body, a tapered extrusion, a Brep, a surface model whose bounds run backwards
    or a face set through its point index; that doesn't join a wall ending short of another; that names types otherwise
    (the file's type, its object type, `(2)` for another thickness, `Imported - Nmm`); or that doesn't leave out a wall
    with no body or no thickness, saying which and why."""
    golden.check(imported(run, workdir, walls_file(), 'ids_of {"ids": [100003, 100004]}',
                          'select_by_id {"text": "2O2Fr$t4X7Zf8NOew3FLOH, 1kTvXnbbzCWw8lcMd1dR4o"}'), "walls.txt")


ANGLES = {
    "radians": ("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)", 3.141592653589793 / 2),
    "degrees": ("IFCCONVERSIONBASEDUNIT(#990001,.PLANEANGLEUNIT.,'DEGREE',#990002)", 90.0),
}


@pytest.mark.parametrize("angle", sorted(ANGLES))
def test_curved_walls_from_trimmed_circles_composite_curves_and_chords(run, workdir, golden, angle):
    """CATCHES: a rewrite that reads a curved wall's arc wrongly: an axis trimmed from a circle by parameters in the
    file's angle unit (radians, or degrees by a conversion), a body whose profile is a composite curve of arcs (one
    run backwards) and trimmed lines, or an axis of chords; its line on the middle of its faces, its thickness from
    their radii, its sweep in degrees."""
    unit, quarter = ANGLES[angle]
    x = Ifc(name="'Curves'", units=(MM, unit))
    x.fixed(990001, "IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0)")
    x.fixed(990002, f"IFCMEASUREWITHUNIT(IFCPLANEANGLEMEASURE(0.017453292519943295),{x.add('IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)')})")
    s, at = x.storey()
    centre = x.add(f"IFCAXIS2PLACEMENT2D({x.pt(0, 0)},$)")

    def arc(r, sense=".T."):
        circle = x.add(f"IFCCIRCLE({centre},{x.mm(r)})")
        return x.add(f"IFCTRIMMEDCURVE({circle},(IFCPARAMETERVALUE(0.)),(IFCPARAMETERVALUE({f(quarter)})),{sense},.PARAMETER.)")

    line = x.add(f"IFCLINE({x.pt(4900, 0)},{x.add(f'IFCVECTOR({x.dir(1, 0)},{x.mm(1)})')})")
    closing = x.add(f"IFCTRIMMEDCURVE({line},({x.pt(4900, 0)}),(IFCPARAMETERVALUE({x.mm(200)})),.T.,.CARTESIAN.)")
    segments = [
        x.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{arc(5100)})"),
        x.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{x.polyline([(0, 5100), (0, 4900)])})"),
        x.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.F.,{arc(4900)})"),
        x.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{closing})"),
    ]
    outline = x.add(f"IFCCOMPOSITECURVE(({','.join(segments)}),.F.)")
    profile = x.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{outline})")
    quarter_wall = x.shape(x.extrude(profile, 3000), axis=arc(5000))
    x.product(f"IFCWALL('c1',$,'Quarter',$,$,{x.place(rel=at)},{quarter_wall},$,$)", s)
    import math
    half = [(20000 + 3000 * math.cos(math.pi * k / 4), 3000 * math.sin(math.pi * k / 4)) for k in range(5)]
    outer = [(20000 + 3150 * math.cos(math.pi * k / 8), 3150 * math.sin(math.pi * k / 8)) for k in range(9)]
    inner = [(20000 + 2850 * math.cos(math.pi * k / 8), 2850 * math.sin(math.pi * k / 8)) for k in range(8, -1, -1)]
    bow = x.shape(x.extrude(x.ring(outer + inner), 2500), axis=x.polyline(half))
    x.product(f"IFCWALL('c2',$,'Bow',$,$,{x.place(rel=at)},{bow},$,$)", s)
    golden.check(imported(run, workdir, x.text(), inspect=False), f"curved_{angle}.txt")


UNITS = {
    "millimetres": ("IFC4", (MM,), 1.0),
    "metres": ("IFC4", ("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)",), 1000.0),
    "centimetres": ("IFC4", ("IFCSIUNIT(*,.LENGTHUNIT.,.CENTI.,.METRE.)",), 10.0),
    "decimetres": ("IFC2X3", ("IFCSIUNIT(*,.LENGTHUNIT.,.DECI.,.METRE.)",), 100.0),
    "kilometres": ("IFC4", ("IFCSIUNIT(*,.LENGTHUNIT.,.KILO.,.METRE.)",), 1e6),
    "micrometres": ("IFC4", ("IFCSIUNIT(*,.LENGTHUNIT.,.MICRO.,.METRE.)",), 1e-3),
    "feet": ("IFC2X3", ("IFCCONVERSIONBASEDUNIT(#990001,.LENGTHUNIT.,'FOOT',#990002)",), 304.8),
    "inches": ("IFC4", ("IFCCONVERSIONBASEDUNITWITHOFFSET(#990001,.LENGTHUNIT.,'INCH',#990002,0.)",), 25.4),
}


@pytest.mark.parametrize("unit", sorted(UNITS))
def test_a_file_in_any_length_unit_comes_in_in_millimetres(run, workdir, golden, unit):
    """CATCHES: a rewrite that ignores the file's length unit or its SI prefix, or misreads a unit converted from metres
    (a foot, an inch): levels, walls, slabs, columns and length properties all come in in millimetres."""
    schema, units, size = UNITS[unit]
    x = Ifc(schema=schema, name=f"'In {unit}'", units=units, unit_mm=size)
    metre = x.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    x.fixed(990001, "IFCDIMENSIONALEXPONENTS(1,0,0,0,0,0,0)")
    x.fixed(990002, f"IFCMEASUREWITHUNIT(IFCLENGTHMEASURE({f(size / 1000)}),{metre})")
    s0, _ = x.storey("'Ground'", 0)
    s1, at1 = x.storey("'First'", 3000)
    wall = x.product(f"IFCWALL('w',$,'Wall',$,$,{x.place(rel=at1)},{x.shape(x.extrude(x.rect(5000, 200, (2500, 0)), 2700), axis=x.polyline([(0, 0), (5000, 0)]))},$,$)", s1)
    slab = x.extrude(x.rect(4000, 3000, (2000, 1500)), 250, at=(0, 0, -250))
    x.product(f"IFCSLAB('f',$,'Slab',$,$,{x.place(rel=at1)},{x.shape(slab)},$,.FLOOR.)", s1)
    x.product(f"IFCCOLUMN('k',$,'C1',$,$,{x.place((6000, 2000, 0), at1)},{x.shape(x.extrude(x.rect(400, 300), 3000))},$,$)", s1)
    cover = x.add(f"IFCPROPERTYSINGLEVALUE('Cover',$,IFCLENGTHMEASURE({x.mm(25)}),$)")
    pset = x.add(f"IFCPROPERTYSET('ps',$,'Pset_Design',$,({cover}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({wall}),{pset})")
    golden.check(imported(run, workdir, x.text(), inspect=False), f"units_{unit}.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Material layers and colours.

def test_layer_sets_become_types_layers_and_materials_take_the_files_colours(run, workdir, golden):
    """CATCHES: a rewrite that reads material layer sets wrongly: the face a wall's usage stacks them from (`.NEGATIVE.`
    or `.POSITIVE.` along its y, turning the wall round so the first layer is on its exterior), a slab's stacked up from
    its bottom, a set on the element's type, what each layer does from its category (or the thickest carrying the rest
    when none says), a layer of no thickness a membrane, at most one variable layer, a set that doesn't add up to the
    element's thickness left out; or that doesn't shade the materials as the file does (a rendering's transparency, an
    IFC2x3 style assignment, a surface style named for its material, colours clamped)."""
    x = Ifc(name="'Layers'")
    s, at = x.storey()
    names = ["Brick", "Insulation", "Concrete", "Plaster", "Gypsum", "Foil", "Screed"]
    mat = {n: x.add(f"IFCMATERIAL('{n}',$,$)") for n in names}

    def layer(m, t, category="$", name="$", description="$"):
        return x.add(f"IFCMATERIALLAYER({mat[m]},{x.mm(t)},$,{name},{description},{category},$)")

    def layers(name, *made):
        return x.add(f"IFCMATERIALLAYERSET(({','.join(made)}),'{name}',$)")

    def wall(name, y, t, length=6000):
        shape = x.shape(x.extrude(x.rect(length, t, (length / 2, y)), 3000), axis=x.polyline([(0, y), (length, y)]))
        return x.product(f"IFCWALL('{name}',$,'{name}',$,$,{x.place(rel=at)},{shape},$,$)", s)

    def associate(what, material):
        x.add(f"IFCRELASSOCIATESMATERIAL('m{x.n}',$,$,$,({what}),{material})")

    outside = layers("Outside 300", layer("Brick", 100, "'Finish'"), layer("Insulation", 50, "'Insulation'"), layer("Concrete", 150, "'LoadBearing'"))
    associate(wall("Negative", 0, 300), x.add(f"IFCMATERIALLAYERSETUSAGE({outside},.AXIS2.,.NEGATIVE.,{x.mm(150)},$)"))
    associate(wall("Positive", -3000, 300), x.add(f"IFCMATERIALLAYERSETUSAGE({outside},.AXIS2.,.POSITIVE.,{x.mm(-150)},$)"))
    untold = layers("Untold 225", layer("Gypsum", 12.5), layer("Concrete", 200), layer("Foil", 0), layer("Gypsum", 12.5))
    typed = wall("Typed", -6000, 225)
    kind = x.add("IFCWALLTYPE('t',$,'Typed 225',$,$,$,$,$,$,.STANDARD.)")
    x.add(f"IFCRELDEFINESBYTYPE('rt',$,$,$,({typed}),{kind})")
    associate(kind, untold)
    associate(wall("Short", -9000, 200), layers("Only 150", layer("Concrete", 150, "'LoadBearing'")))
    associate(wall("Odd", -12000, 100), layers("Odd 100", layer("Plaster", 10, "'Substrate'"), layer("Foil", 0, "'Membrane'"), layer("Gypsum", 90, "'Partition'")))
    slab = x.shape(x.extrude(x.rect(4000, 3000, (2000, 5000)), 200, at=(0, 0, -200)))
    floor = x.product(f"IFCSLAB('f1',$,'Bottom up',$,$,{x.place(rel=at)},{slab},$,.FLOOR.)", s)
    stack = layers("Slab 200", layer("Plaster", 20, "'Finish'"), layer("Concrete", 180, "'LoadBearing'"))
    associate(floor, x.add(f"IFCMATERIALLAYERSETUSAGE({stack},.AXIS3.,.POSITIVE.,0.,$)"))
    slab = x.shape(x.extrude(x.rect(4000, 3000, (7000, 5000)), 230, at=(0, 0, -230)))
    floor = x.product(f"IFCSLAB('f2',$,'Terrace',$,$,{x.place(rel=at)},{slab},$,.FLOOR.)", s)
    kind = x.add("IFCSLABTYPE('t2',$,'Terrace 230',$,$,$,$,$,$,.FLOOR.)")
    x.add(f"IFCRELDEFINESBYTYPE('rt2',$,$,$,({floor}),{kind})")
    associate(kind, layers("Terrace 230", layer("Screed", 50, "'Finish'", name="'variable'"), layer("Insulation", 30, "'Insulation'", description="'Variable'"), layer("Concrete", 150, "'LoadBearing'")))
    ceiling = x.shape(x.extrude(x.rect(4000, 3000, (2000, 9000)), 50, at=(0, 0, 2700)))
    covering = x.product(f"IFCCOVERING('c1',$,'Ceiling',$,$,{x.place(rel=at)},{ceiling},$,.CEILING.)", s)
    associate(covering, layers("Ceiling 50", layer("Gypsum", 12.5, "'Finish'"), layer("Insulation", 37.5, "'Insulation'")))

    def colour(r, g, b):
        return x.add(f"IFCCOLOURRGB($,{f(r)},{f(g)},{f(b)})")

    # IFC4: the material's own representation, a rendering a quarter see-through.
    style = x.add(f"IFCSURFACESTYLE('Brick red',.BOTH.,({x.add(f'IFCSURFACESTYLERENDERING({colour(0.6, 0.2, 0.1)},0.25,$,$,$,$,$,$,.NOTDEFINED.)')}))")
    item = x.add(f"IFCSTYLEDITEM($,({style}),$)")
    x.add(f"IFCMATERIALDEFINITIONREPRESENTATION($,$,({x.add(f'IFCSTYLEDREPRESENTATION($,$,$,({item}))')}),{mat['Brick']})")
    # IFC2x3: through a presentation style assignment, a shading.
    style = x.add(f"IFCSURFACESTYLE($,.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({colour(0.9, 0.9, 0.8)})')}))")
    item = x.add(f"IFCSTYLEDITEM($,({x.add(f'IFCPRESENTATIONSTYLEASSIGNMENT(({style}))')}),$)")
    x.add(f"IFCMATERIALDEFINITIONREPRESENTATION($,$,({x.add(f'IFCSTYLEDREPRESENTATION($,$,$,({item}))')}),{mat['Plaster']})")
    # Surface styles named as the materials are; one out of range, clamped.
    x.add(f"IFCSURFACESTYLE('Gypsum',.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({colour(1.5, -0.2, 0.5)},0.)')}))")
    x.add(f"IFCSURFACESTYLE('Concrete',.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({colour(0.5, 0.5, 0.5)},1.)')}))")
    # An RGB colour missing its green: no colour.
    x.add(f"IFCSURFACESTYLE('Screed',.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({x.add(chr(73) + 'FCCOLOURRGB($,1.,$,0.5)')},0.)')}))")
    # Shaded in a predefined colour, which isn't an RGB one, and styled with a curve style: no colour from either.
    named = x.add("IFCDRAUGHTINGPREDEFINEDCOLOUR('red')")
    x.add(f"IFCSURFACESTYLE('Insulation',.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({named},0.)')},{x.add(chr(73) + 'FCCURVESTYLE($,$,$,$,$)')}))")
    item = x.add(f"IFCSTYLEDITEM($,({x.add('IFCCURVESTYLE($,$,$,$,$)')}),$)")
    x.add(f"IFCMATERIALDEFINITIONREPRESENTATION($,$,({x.add(f'IFCSTYLEDREPRESENTATION($,$,$,({item}))')}),{mat['Foil']})")
    golden.check(imported(run, workdir, x.text()), "layers.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Floors, ceilings, roofs and the holes in them.

def holed(slab, within):
    """An IFC4 file in mm with a 6 x 4 m slab 200 mm thick, its profile round two holes, an opening element voiding it
    through the east one, as a mesh would carry it: `slab` makes the slab #35, and what it's part of; the storey holds
    `within`."""
    def rect(n, x0, y0, x1, y1):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        made = "\n".join(f"#{n + 1 + i}=IFCCARTESIANPOINT(({px:.1f},{py:.1f}));" for i, (px, py) in enumerate(pts))
        return f"{made}\n#{n}=IFCPOLYLINE((#{n + 1},#{n + 2},#{n + 3},#{n + 4},#{n + 1}));"

    return f"""ISO-10303-21;HEADER;FILE_SCHEMA(('IFC4'));ENDSEC;DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCPROJECT('p',$,'Holes',$,$,$,$,$,#2);
#4=IFCCARTESIANPOINT((0.,0.,-200.));
#5=IFCAXIS2PLACEMENT3D(#4,$,$);
#6=IFCLOCALPLACEMENT($,#5);
#7=IFCBUILDINGSTOREY('s',$,'Level 0',$,$,$,$,$,.ELEMENT.,0.);
{rect(10, 0, 0, 6000, 4000)}
{rect(20, 1000, 1000, 2500, 2000)}
{rect(25, 4000, 1000, 5000, 2000)}
#30=IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,#10,(#20,#25));
#31=IFCDIRECTION((0.,0.,1.));
#32=IFCEXTRUDEDAREASOLID(#30,$,#31,200.);
#33=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#32));
#34=IFCPRODUCTDEFINITIONSHAPE($,$,(#33));
{slab}
#40=IFCCARTESIANPOINT((4500.,1500.));
#41=IFCAXIS2PLACEMENT2D(#40,$);
#42=IFCRECTANGLEPROFILEDEF(.AREA.,$,#41,1000.,1000.);
#43=IFCEXTRUDEDAREASOLID(#42,$,#31,200.);
#44=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#43));
#45=IFCPRODUCTDEFINITIONSHAPE($,$,(#44));
#46=IFCOPENINGELEMENT('o',$,'Hole',$,$,#6,#45,$,.OPENING.);
#47=IFCRELVOIDSELEMENT('v',$,$,$,#35,#46);
#50=IFCRELCONTAINEDINSPATIALSTRUCTURE('r',$,$,$,(#{within}),#7);
ENDSEC;END-ISO-10303-21;"""


HOLED = {
    "slab": ("#35=IFCSLAB('f',$,'Slab',$,$,#6,#34,$,.FLOOR.);", 35),
    "ceiling": ("#35=IFCCOVERING('f',$,'Ceiling',$,$,#6,#34,$,.CEILING.);", 35),
    "roof": ("#35=IFCROOF('f',$,'Roof',$,$,#6,#34,$,.FLAT_ROOF.);", 35),
    "roof_slab_part_of_a_roof": ("#35=IFCSLAB('f',$,'Slab',$,$,#6,#34,$,.ROOF.);\n#36=IFCROOF('r',$,'Roof',$,$,#6,$,$,.FLAT_ROOF.);\n"
                                 "#37=IFCRELAGGREGATES('a',$,$,$,#36,(#35));", 36),
    "slab_typed_roof_on_its_own": ("#35=IFCSLAB('f',$,'Slab',$,$,#6,#34,$,.ROOF.);", 35),
    "landing_on_its_own": ("#35=IFCSLAB('f',$,'L1',$,$,#6,#34,$,.LANDING.);", 35),
}


@pytest.mark.parametrize("case", sorted(HOLED))
def test_holes_in_a_slab_are_its_openings_or_the_shafts_through_it(run, workdir, golden, case):
    """CATCHES: a rewrite that loses the holes of a profile with voids, doesn't tell the hole an opening element cuts
    (a shaft, through whatever it voids) from the slab's own (an opening of the floor, ceiling or roof), or reads a roof
    slab (on its own or as a roof's part), a ceiling covering or a landing on its own as something else."""
    slab, within = HOLED[case]
    golden.check(imported(run, workdir, holed(slab, within), inspect=False), f"holed_{case}.txt")


def test_sloped_stepped_and_odd_slabs(run, workdir, golden):
    """CATCHES: a rewrite that reads a slab whose top slopes (a Brep) as level, or measures its slope, its arrow up the
    slope and its thickness square to it wrongly; that makes a floor of a slab with no top facing up instead of leaving
    it out (`its top isn't flat`); that reads a ceiling whose top isn't level, or a roof with an underside that isn't
    parallel to its top, instead of saying so; or that loses which slab is structural (`LoadBearing` in its common set)."""
    x = Ifc(name="'Slabs'")
    s, at = x.storey()
    x.storey("'Above'", 3000)
    # Sloping up east 1 in 10, 200 mm deep plumb.
    lo, hi = (lambda px: px / 10), (lambda px: px / 10 - 200)
    c = [(0, 0), (4000, 0), (4000, 3000), (0, 3000)]
    top = [(p[0], p[1], lo(p[0])) for p in c]
    bottom = [(p[0], p[1], hi(p[0])) for p in reversed(c)]
    sides = [[(a[0], a[1], hi(a[0])), (b[0], b[1], hi(b[0])), (b[0], b[1], lo(b[0])), (a[0], a[1], lo(a[0]))] for a, b in zip(c, c[1:] + c[:1])]
    ramp = x.product(f"IFCSLAB('f1',$,'Ramp',$,$,{x.place(rel=at)},{x.shape(x.brep([top, bottom, *sides]), kind='Brep')},$,.FLOOR.)", s)
    common = x.add(f"IFCPROPERTYSET('ps',$,'Pset_SlabCommon',$,({x.add('IFCPROPERTYSINGLEVALUE(' + chr(39) + 'LoadBearing' + chr(39) + ',$,IFCBOOLEAN(.T.),$)')}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({ramp}),{common})")
    # Only its sides: nothing faces up.
    walls_only = [f for f in box(6000, 0, -200, 9000, 3000, 0)[2:]]
    x.product(f"IFCSLAB('f2',$,'Sides',$,$,{x.place(rel=at)},{x.shape(x.brep(walls_only), kind='Brep')},$,.FLOOR.)", s)
    x.product(f"IFCSLAB('f3',$,'Nothing',$,$,{x.place(rel=at)},$,$,.FLOOR.)", s)
    tilted = [(p[0] + 12000, p[1], 2700 + p[0] / 10) for p in c]
    ceiling = [tilted, [(p[0], p[1], p[2] - 20) for p in reversed(tilted)]]
    x.product(f"IFCCOVERING('c1',$,'Tilted',$,$,{x.place(rel=at)},{x.shape(x.brep(ceiling), kind='Brep')},$,.CEILING.)", s)
    x.product(f"IFCCOVERING('c2',$,'Empty',$,$,{x.place(rel=at)},$,$,.CEILING.)", s)
    x.product(f"IFCCOVERING('c3',$,'Cladding',$,$,{x.place(rel=at)},$,$,.CLADDING.)", s)
    # A roof sloping one way on top, level underneath.
    roof_top = [(p[0] + 18000, p[1], 3300 + p[0] / 10) for p in c]
    roof = [roof_top, [(p[0], p[1], 3000) for p in reversed(roof_top)]]
    x.product(f"IFCROOF('r1',$,'Wedge',$,$,{x.place(rel=at)},{x.shape(x.brep(roof), kind='Brep')},$,.SHED_ROOF.)", s)
    x.product(f"IFCROOF('r2',$,'Air',$,$,{x.place(rel=at)},$,$,.FLAT_ROOF.)", s)
    golden.check(imported(run, workdir, x.text(), inspect=False), "slabs.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Columns and footings.

def test_columns_by_their_section_whatever_profile_draws_it(run, workdir, golden):
    """CATCHES: a rewrite that sizes a column wrongly from its profile (a rectangle turned with its placement, a circle
    or a hollow one as round, a steel I, L or U section by its bounding rectangle, an ellipse, a profile derived by a
    scaling operator), that doesn't make one that carries load a structural column or an isolated footing a footing,
    names the types otherwise (`Imported W x D`, `Imported Round D`, the file's type), or reaches the wrong top level."""
    x = Ifc(name="'Columns'")
    s, at = x.storey("'Ground'", 0)
    x.storey("'First'", 3000)

    def column(name, profile, xy, cls="IFCCOLUMN", turn=None, height=3000, last="$"):
        place = x.place((xy[0], xy[1], 0), at, x=turn)
        return x.product(f"{cls}('{name}',$,'{name}',$,$,{place},{x.shape(x.extrude(profile, height))},$,{last})", s)

    column("Turned", x.rect(400, 300), (0, 0), turn=(0.8660254037844387, 0.5, 0))
    column("Round", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(150)})"), (2000, 0))
    column("Tube", x.add(f"IFCCIRCLEHOLLOWPROFILEDEF(.AREA.,$,$,{x.mm(100)},{x.mm(10)})"), (4000, 0))
    column("Steel I", x.add(f"IFCISHAPEPROFILEDEF(.AREA.,$,$,{x.mm(200)},{x.mm(300)},10.,15.,$,$,$)"), (6000, 0), cls="IFCCOLUMNSTANDARDCASE")
    column("Angle", x.add(f"IFCLSHAPEPROFILEDEF(.AREA.,$,$,{x.mm(150)},{x.mm(100)},10.,$,$,$,$)"), (8000, 0))
    column("Channel", x.add(f"IFCUSHAPEPROFILEDEF(.AREA.,$,$,{x.mm(250)},{x.mm(80)},8.,12.,$,$,$)"), (10000, 0))
    column("Oval", x.add(f"IFCELLIPSEPROFILEDEF(.AREA.,$,$,{x.mm(200)},{x.mm(100)})"), (12000, 0))
    op = x.add(f"IFCCARTESIANTRANSFORMATIONOPERATOR2D($,$,{x.pt(0, 0)},2.)")
    column("Doubled", x.add(f"IFCDERIVEDPROFILEDEF(.AREA.,$,{x.rect(100, 100)},{op},$)"), (14000, 0))
    column("Rounded", x.add(f"IFCROUNDEDRECTANGLEPROFILEDEF(.AREA.,$,$,{x.mm(500)},{x.mm(500)},{x.mm(50)})"), (16000, 0))
    loaded = column("P1", x.rect(200, 500), (0, 4000))
    common = x.add(f"IFCPROPERTYSET('ps',$,'Pset_ColumnCommon',$,({x.add(chr(73) + 'FCPROPERTYSINGLEVALUE(' + chr(39) + 'LoadBearing' + chr(39) + ',$,IFCBOOLEAN(.T.),$)')}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({loaded}),{common})")
    typed = column("Typed", x.rect(300, 300), (2000, 4000), height=2500)
    kind = x.add("IFCCOLUMNTYPE('t',$,'Square 300',$,$,$,$,$,$,.COLUMN.)")
    x.add(f"IFCRELDEFINESBYTYPE('rt',$,$,$,({typed}),{kind})")
    column("Pad", x.rect(1200, 1000), (0, 8000), cls="IFCFOOTING", height=400, last=".PAD_FOOTING.")
    x.product(f"IFCCOLUMN('Ghost',$,'Ghost',$,$,{x.place(rel=at)},$,$,$)", s)
    golden.check(imported(run, workdir, x.text()), "columns.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Runs: beams, strip footings, pipes, ducts, conduits, trays, wires.

def test_runs_found_along_their_bodies_by_class_type_and_property_set(run, workdir, golden):
    """CATCHES: a rewrite that finds a run's centre line or section wrongly (a beam extruded along its own x however
    short, a round pipe, a swept disk along an indexed polycurve through a mapped item, a sloped beam's two heights);
    that picks the wrong category from the class and predefined type (a tray, a ladder, a conduit, a strip footing) or
    ignores BIMCraft's own set (its category and justification); that loses the system a run is assigned to or the
    library material it is made of; or that doesn't leave out an upright beam, a run too short or one with no body."""
    x = Ifc(name="'Runs'")
    s, at = x.storey()

    def run_of(cls, name, profile, depth, xyz, along=(1, 0, 0), last="$", turn=None):
        across = (0, 1, 0) if abs(along[1]) < 0.5 else (1, 0, 0)
        body = x.shape(x.extrude(profile, depth, z=along, xdir=across))
        return x.product(f"{cls}('{name}',$,'{name}',$,$,{x.place(xyz, at, x=turn)},{body},$,{last})", s)

    beam = run_of("IFCBEAM", "V1", x.rect(400, 140, (0, 0)), 3000, (0, 0, 2800))
    concrete = x.add("IFCMATERIAL('Concrete',$,$)")
    profiles = x.add(f"IFCMATERIALPROFILESET($,$,({x.add(f'IFCMATERIALPROFILE($,$,{concrete},$,$,$)')}),$)")
    x.add(f"IFCRELASSOCIATESMATERIAL('m1',$,$,$,({beam}),{x.add(f'IFCMATERIALPROFILESETUSAGE({profiles},5,$)')})")
    run_of("IFCBEAM", "V2", x.rect(140, 400), 3000, (5000, 0, 0), along=(0, 0, 1))
    run_of("IFCBEAMSTANDARDCASE", "V3", x.rect(300, 200), 4000, (0, 2000, 3000), along=(0.9950371902099892, 0, 0.09950371902099892))
    pipe = run_of("IFCPIPESEGMENT", "Cold", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(25)})"), 4000, (0, 4000, 500), along=(0, 1, 0), last=".RIGIDSEGMENT.")
    system = x.add("IFCSYSTEM('sy',$,'Cold water',$,$)")
    x.add(f"IFCRELASSIGNSTOGROUP('g1',$,$,$,({pipe}),$,{system})")
    duct = run_of("IFCDUCTSEGMENT", "Supply", x.rect(200, 300), 5000, (2000, 9000, 2600), last=".RIGIDSEGMENT.")
    networks = x.add("IFCDISTRIBUTIONSYSTEM('ds',$,'Supply air',$,$,$,.VENTILATION.)")
    x.add(f"IFCRELASSIGNSTOGROUP('g2',$,$,$,({duct}),$,{networks})")
    said = [x.add(f"IFCPROPERTYSINGLEVALUE('Justification',$,IFCTEXT('top'),$)"), x.add("IFCPROPERTYSINGLEVALUE('Category',$,IFCTEXT('duct'),$)")]
    own = x.add(f"IFCPROPERTYSET('ps',$,'BIMCraft_Run',$,({','.join(said)}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({duct}),{own})")
    run_of("IFCCABLECARRIERSEGMENT", "Tray", x.rect(300, 100), 6000, (0, 10000, 2700), last=".CABLETRAYSEGMENT.")
    run_of("IFCCABLECARRIERSEGMENT", "Ladder", x.rect(400, 80), 6000, (0, 11000, 2700), last=".CABLELADDERSEGMENT.")
    run_of("IFCCABLECARRIERSEGMENT", "Conduit", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(12.5)})"), 6000, (0, 12000, 2500), last=".CONDUITSEGMENT.")
    run_of("IFCFOOTING", "Strip", x.rect(600, 400), 6000, (0, 14000, -400), last=".STRIP_FOOTING.")
    earth = run_of("IFCCABLESEGMENT", "Earth", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(5)})"), 6000, (0, 15000, -500), last=".CONDUCTORSEGMENT.")
    own = x.add(f"IFCPROPERTYSET('ps2',$,'BIMCraft_Run',$,({x.add(chr(73) + 'FCPROPERTYSINGLEVALUE(' + chr(39) + 'Category' + chr(39) + ',$,IFCTEXT(' + chr(39) + 'groundconductor' + chr(39) + '),$)')}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp2',$,$,$,({earth}),{own})")
    # As Renga writes a cable: a disk 3.7 mm across swept along an indexed polycurve, through a mapped item.
    points = x.add(f"IFCCARTESIANPOINTLIST3D((({x.mm(0)},0.,0.),({x.mm(3000)},0.,0.)))")
    curve = x.add(f"IFCINDEXEDPOLYCURVE({points},(IFCLINEINDEX((1,2))),$)")
    disk = x.add(f"IFCSWEPTDISKSOLID({curve},{x.mm(3.7)},$,$,$)")
    rep = x.add(f"IFCSHAPEREPRESENTATION($,'Body','AdvancedSweptSolid',({disk}))")
    mapped = x.add(f"IFCMAPPEDITEM({x.add(f'IFCREPRESENTATIONMAP({x.world},{rep})')},{x.add(f'IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,{x.origin},$,$)')})")
    x.product(f"IFCCABLESEGMENT('k',$,'Cable',$,$,{x.place((1000, 16000, 2900), at)},{x.shape(mapped, kind='MappedRepresentation')},$,.CABLESEGMENT.)", s)
    odd = run_of("IFCPIPESEGMENT", "Odd set", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(25)})"), 4000, (0, 20000, 500), along=(0, 1, 0), last=".RIGIDSEGMENT.")
    said = [x.add("IFCPROPERTYSINGLEVALUE('Justification',$,IFCREAL(1.),$)"), x.add("IFCPROPERTYSINGLEVALUE('Category',$,$,$)")]
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp3',$,$,$,({odd}),{x.add(f'IFCPROPERTYSET(' + chr(39) + 'ps3' + chr(39) + ',$,' + chr(39) + 'BIMCraft_Run' + chr(39) + ',$,(' + ','.join(said) + '))')})")
    copper = x.add("IFCMATERIAL('Copper',$,$)")
    parts = x.add(f"IFCMATERIALCONSTITUENTSET('Pipe',$,({x.add(f'IFCMATERIALCONSTITUENT($,$,{copper},$,$)')}))")
    x.add(f"IFCRELASSOCIATESMATERIAL('m2',$,$,$,({pipe}),{parts})")
    nested = copper
    for _ in range(9):
        nested = x.add(f"IFCMATERIALLIST(({nested}))")
    x.add(f"IFCRELASSOCIATESMATERIAL('m3',$,$,$,({odd}),{nested})")
    x.add(f"IFCRELASSOCIATESMATERIAL('m4',$,$,$,({duct}),{x.add('IFCMATERIALPROPERTIES($,$,(),' + copper + ')')})")
    run_of("IFCPIPESEGMENT", "Stub", x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(25)})"), 0.5, (0, 18000, 500), last=".RIGIDSEGMENT.")
    x.product(f"IFCPIPESEGMENT('n',$,'Nothing',$,$,{x.place(rel=at)},$,$,.RIGIDSEGMENT.)", s)
    golden.check(imported(run, workdir, x.text()), "runs.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Components: furniture, fixtures, devices, proxies.

def test_furniture_fixtures_and_proxies_become_components_of_families_made_of_their_bodies(run, workdir, golden):
    """CATCHES: a rewrite that doesn't make a family of each name the file gives (`Family:Type`, the type's name over the
    product's), a type of each shape (`A`, `A (2)`… with a Variant parameter), a mirror image of a type that type
    mirrored, a family of the category the class, predefined type or object type says (a basin a `lav`, a lightning
    terminal, a rack), forms grouped by the styles their items wear; or that places a component elsewhere (its point,
    angle and offset) or keeps one with no body."""
    x = Ifc(name="'Furnished'")
    s, at = x.storey()
    x.storey("'Upper'", 3000)

    def thing(cls, name, xyz, profile, depth=400, turn=None, object_type="$", last="$", styles=()):
        solid = x.extrude(profile, depth)
        items = [solid]
        for style in styles:
            other = x.extrude(x.rect(100, 100, (0, 0)), 50, at=(0, 0, depth))
            x.add(f"IFCSTYLEDITEM({other},({style}),$)")
            items.append(other)
        return x.product(f"{cls}('{name}{x.n}',$,'{name}',$,{object_type},{x.place(xyz, at, x=turn)},{x.shape(*items, kind='SweptSolid')},$,{last})", s)

    square = [(0, 0), (300, 0), (300, 300), (0, 300)]
    for k in range(3):
        thing("IFCBUILDINGELEMENTPROXY", "Thing:A", (k * 1000, 0, 0), x.ring([(px * (1 + k / 10), py * (1 + k / 10)) for px, py in square]))
    # A wedge and its mirror image, written as triangles: the second is the first's type, mirrored.
    timber = x.add(f"IFCSURFACESTYLE('Timber',.BOTH.,({x.add(f'IFCSURFACESTYLESHADING({x.add(chr(73) + 'FCCOLOURRGB($,0.5,0.3,0.1)')},0.)')}))")

    def wedge(name, xyz, flip):
        corners = [(0, 0, 0), (400, 0, 0), (0, 300, 0), (0, 0, 500)]
        tris = [(1, 3, 2), (1, 2, 4), (1, 4, 3), (2, 3, 4)]
        if flip:
            corners = [(px, -py, pz) for px, py, pz in corners]
            tris = [(a, c, b) for a, b, c in tris]
        pts = x.add(f"IFCCARTESIANPOINTLIST3D(({','.join('(' + ','.join(x.mm(c) for c in p) + ')' for p in corners)}))")
        mesh = x.add(f"IFCTRIANGULATEDFACESET({pts},$,.T.,({','.join(str(t).replace(' ', '') for t in tris)}),$)")
        x.add(f"IFCSTYLEDITEM({mesh},({timber}),$)")
        return x.product(f"IFCFURNISHINGELEMENT('{name}',$,'{name}',$,$,{x.place(xyz, at, x=(0, 1, 0))},{x.shape(mesh, kind='Tessellation')},$,$)", s)

    chair, mirrored = wedge("Chair 1", (0, 3000, 0), False), wedge("Chair 2", (2000, 3000, 0), True)
    kind = x.add("IFCFURNISHINGELEMENTTYPE('ct',$,'Chair:Basic',$,$,$,$,$,$)")
    x.add(f"IFCRELDEFINESBYTYPE('rt',$,$,$,({chair},{mirrored}),{kind})")
    thing("IFCSYSTEMFURNITUREELEMENT", "Desk:Long", (5000, 3000, 750), x.rect(1600, 800, (800, 400)), depth=30)
    thing("IFCSANITARYTERMINAL", "Basin", (0, 6000, 800), x.rect(500, 400), depth=150, last=".WASHHANDBASIN.")
    thing("IFCSANITARYTERMINAL", "Tub", (2000, 6000, 0), x.rect(1600, 700), depth=500, last=".BATH.")
    thing("IFCWASTETERMINAL", "Drain", (4000, 6000, 0), x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(50)})"), depth=20, last=".FLOORTRAP.")
    thing("IFCPIPEFITTING", "Elbow", (6000, 6000, 500), x.rect(100, 100), depth=100, last=".BEND.")
    thing("IFCVALVE", "Valve", (7000, 6000, 500), x.rect(80, 80), depth=120)
    thing("IFCELECTRICDISTRIBUTIONBOARD", "Board", (0, 9000, 1200), x.rect(400, 120), depth=600, last=".DISTRIBUTIONBOARD.")
    thing("IFCOUTLET", "Socket", (1000, 9000, 300), x.rect(80, 40), depth=80, last=".POWEROUTLET.")
    thing("IFCOUTLET", "Data", (2000, 9000, 300), x.rect(80, 40), depth=80, last=".DATAOUTLET.")
    thing("IFCOUTLET", "Phone", (3000, 9000, 300), x.rect(80, 40), depth=80, last=".TELEPHONEOUTLET.")
    thing("IFCSWITCHINGDEVICE", "Switch", (4000, 9000, 1100), x.rect(80, 40), depth=80, last=".TOGGLESWITCH.")
    thing("IFCCOMMUNICATIONSAPPLIANCE", "Patch", (5000, 9000, 1800), x.rect(480, 300), depth=44, last=".NETWORKAPPLIANCE.")
    thing("IFCLIGHTFIXTURE", "Lamp", (6000, 9000, 2600), x.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,$,{x.mm(150)})"), depth=100,
          styles=[x.add("IFCCURVESTYLE($,$,$,$,$)")])
    thing("IFCBUILDINGELEMENTPROXY", "Captor:Franklin", (0, 12000, 6000), x.rect(50, 50), depth=1000, object_type="'LightningTerminal'", last=".USERDEFINED.")
    thing("IFCBUILDINGELEMENTPROXY", "Rod", (1000, 12000, -2400), x.rect(20, 20), depth=2400, object_type="'EarthingRod'", last=".USERDEFINED.")
    thing("IFCBUILDINGELEMENTPROXY", "Pit", (2000, 12000, -300), x.rect(300, 300), depth=300, object_type="'InspectionBox'", last=".USERDEFINED.")
    thing("IFCBUILDINGELEMENTPROXY", "Cabinet", (3000, 12000, 0), x.rect(600, 800), depth=2000, object_type="'Rack'", last=".USERDEFINED.")
    thing("IFCFURNISHINGELEMENT", "Shelf", (0, 15000, 3000), x.rect(900, 300), depth=1800)
    x.product(f"IFCFURNISHINGELEMENT('ghost',$,'Ghost',$,$,{x.place(rel=at)},$,$)", s)
    golden.check(imported(run, workdir, x.text()), "components.txt")


def test_a_family_name_with_no_family_or_no_type_leaves_its_components_out(run, workdir, golden):
    """CATCHES: a rewrite that makes a family of no name or a type of no name from a product named `:Type` or `Family:`
    instead of leaving its components out with the family's rule, or that doesn't cut a family's and a type's name to
    the 256 characters a name may hold."""
    x = Ifc(name="'Families'")
    s, at = x.storey()
    for k, name in enumerate([":Alone", "Family:", " : ", "Fam:" + "T" * 300, "x" * 300 + ":T"]):
        solid = x.extrude(x.rect(100, 100), 100)
        x.product(f"IFCBUILDINGELEMENTPROXY('g{k}',$,'{name}',$,$,{x.place((k * 1000, 0, 0), at)},{x.shape(solid)},$,.ELEMENT.)", s)
    golden.check(imported(run, workdir, x.text(), inspect=False), "family_names.txt")


def test_more_shapes_of_one_family_than_it_holds_leave_only_the_rest_out(run, workdir, golden):
    """CATCHES: a rewrite that lets a family grow past the 256 forms one may hold, or leaves the whole family out, instead
    of leaving out only the components past it, each saying so."""
    x = Ifc(name="'Many'")
    s, at = x.storey()
    for k in range(259):
        solid = x.extrude(x.rect(100 + k, 100), 100)
        x.product(f"IFCBUILDINGELEMENTPROXY('g{k}',$,'Thing:A',$,$,{x.place((k * 1000, 0, 0), at)},{x.shape(solid)},$,.ELEMENT.)", s)
    (workdir / "many.ifc").write_text(x.text())
    golden.check_run(run(["run", "many.ifc", "--cmd", 'elements {"category": "component", "offset": 255}']), "many_shapes.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Rooms, grids, room separation lines.

def test_spaces_become_rooms_named_and_numbered_with_their_colour(run, workdir, golden):
    """CATCHES: a rewrite that names or numbers rooms differently (a space's name is its number and its long name its
    name; one alone is the name, numbered on after the others; neither is `Room`), places one elsewhere (inside its
    footprint, at its placement without a body, on the storey it is aggregated to), loses the colour its body is styled
    in, or keeps one with no footprint."""
    x = Ifc(name="'Rooms'")
    s0, at0 = x.storey("'Ground'", 0)
    s1, at1 = x.storey("'Upper'", 3000)

    def space(name, long, at, body=None):
        shape = x.shape(body, kind="SweptSolid") if body else "$"
        return x.add(f"IFCSPACE('sp{x.n}',$,{name},$,$,{x.place(rel=at)},{shape},{long},.ELEMENT.,.INTERNAL.,$)")

    rooms = [
        space("'101'", "'Office'", at0, x.extrude(x.ring([(0, 0), (4000, 0), (4000, 3000), (0, 3000)]), 2700)),
        space("'Store'", "$", at0, x.extrude(x.ring([(5000, 0), (8000, 0), (8000, 2000), (6000, 2000), (6000, 4000), (5000, 4000)]), 2700)),
        space("$", "$", at0, x.extrude(x.rect(2000, 2000, (10000, 1000)), 2700)),
        space("$", "'Hall'", at0),
    ]
    painted = x.extrude(x.rect(3000, 3000, (1500, 1500)), 2700)
    x.add(f"IFCSTYLEDITEM({painted},({x.add(f'IFCSURFACESTYLE($,.BOTH.,({x.add(chr(73) + 'FCSURFACESTYLESHADING(' + x.add('IFCCOLOURRGB($,0.84,0.9,0.82)') + ',0.)')}))')}),$)")
    upper = [space("'201'", "'Studio'", at1, painted)]
    sheet = [(0, 0, 0), (3000, 0, 0), (3000, 0, 2700), (0, 0, 2700)]
    loop = x.add(f"IFCPOLYLOOP(({','.join(x.pt(*p) for p in sheet)}))")
    face = x.add(f"IFCFACE(({x.add(f'IFCFACEOUTERBOUND({loop},.T.)')}))")
    upper.append(space("'202'", "'Flat'", at1, x.add(f"IFCFACEBASEDSURFACEMODEL(({x.add(f'IFCCONNECTEDFACESET(({face}))')}))")))
    x.add(f"IFCRELAGGREGATES('a0',$,$,$,{s0},({','.join(rooms)}))")
    x.add(f"IFCRELAGGREGATES('a1',$,$,$,{s1},({','.join(upper)}))")
    golden.check(imported(run, workdir, x.text(), inspect=False), "spaces.txt")


def test_grids_and_room_separation_lines(run, workdir, golden):
    """CATCHES: a rewrite that loses a grid's axes (their tags, a missing tag numbered, an axis run backwards when its
    sense is false, a repeated tag made unique, the grid's own placement), or doesn't make a room separation line for
    each segment of a BIMCraft virtual element's axis, leaving out one with no axis."""
    x = Ifc(name="'Grids'")
    s, at = x.storey()

    def axis(tag, a, b, sense=".T."):
        return x.add(f"IFCGRIDAXIS({tag},{x.polyline([a, b])},{sense})")

    us = [axis("'1'", (0, -1000), (0, 9000)), axis("'2'", (5000, -1000), (5000, 9000), ".F."), axis("'2'", (10000, -1000), (10000, 9000))]
    vs = [axis("'A'", (-1000, 0), (11000, 0)), axis("$", (-1000, 8000), (11000, 8000))]
    ws = [axis("'X'", (-1000, -1000), (11000, 9000))]
    x.product(f"IFCGRID('g',$,'Grid',$,$,{x.place((100000, 0, 0), at)},$,({','.join(us)}),({','.join(vs)}),({','.join(ws)}))", s)
    line = x.shape(x.polyline([(0, 0), (3000, 0), (3000, 3000), (3000, 3000)]), ident="Axis", kind="Curve2D")
    x.product(f"IFCVIRTUALELEMENT('v1',$,'Room Separation Line',$,'RoomSeparation',{x.place(rel=at)},{line},$)", s)
    x.product(f"IFCVIRTUALELEMENT('v2',$,'Room Separation Line',$,'RoomSeparation',{x.place(rel=at)},$,$)", s)
    x.product(f"IFCVIRTUALELEMENT('v3',$,'Space boundary',$,'Other',{x.place(rel=at)},{line},$)", s)
    golden.check(imported(run, workdir, x.text(), inspect=False), "grids.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Doors and windows.

def test_doors_and_windows_where_their_openings_cut_their_walls(run, workdir, golden):
    """CATCHES: a rewrite that places a door or window elsewhere along its wall or at another sill, sizes it otherwise (its
    overall width and height, else its opening's body, else its own), reads how a door opens wrongly (its own operation,
    its IFC4 type's, its IFC2x3 style's, which hand), takes a tag that is only its id or another's as its mark, or keeps
    one that isn't in a wall, whose wall was left out, that overlaps another, or that rises past its wall's top (said
    with the file's wall and both heights)."""
    x = Ifc(name="'Openings'")
    s, at = x.storey()
    wall = x.product(f"IFCWALL('w',$,'Long',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(16000, 200, (8000, 0)), 3000), axis=x.polyline([(0, 0), (16000, 0)]))},$,$)", s)
    ghost = x.product(f"IFCWALL('wg',$,'Ghost',$,$,{x.place(rel=at)},$,$,$)", s)

    def opening(host, x0, width, z0, height):
        body = x.shape(x.extrude(x.rect(width, 400, (x0 + width / 2, 0)), height, at=(0, 0, z0)))
        o = x.add(f"IFCOPENINGELEMENT('o{x.n}',$,'Opening',$,$,{x.place(rel=at)},{body},$,.OPENING.)")
        x.add(f"IFCRELVOIDSELEMENT('v{x.n}',$,$,$,{host},{o})")
        return o

    def fill(o, entity):
        filled = x.product(entity, s)
        x.add(f"IFCRELFILLSELEMENT('f{x.n}',$,$,$,{o},{filled})")
        return filled

    def door(name, o, tag="$", h="$", w="$", op="$"):
        return fill(o, f"IFCDOOR('{name}',$,'{name}',$,$,{x.place(rel=at)},$,{tag},{h},{w},.DOOR.,{op},$)")

    door("Right", opening(wall, 500, 900, 0, 2100), "'D1'", x.mm(2100), x.mm(900), ".SINGLE_SWING_RIGHT.")
    typed = door("Slider", opening(wall, 2000, 1200, 0, 2100), "'D1'")
    kind = x.add("IFCDOORTYPE('dt',$,'Slide 1200',$,$,$,$,$,$,.DOOR.,.SLIDING_TO_LEFT.,.T.,$)")
    x.add(f"IFCRELDEFINESBYTYPE('r1',$,$,$,({typed}),{kind})")
    styled = door("Double", opening(wall, 4000, 1600, 0, 2100), "'D3'")
    style = x.add("IFCDOORSTYLE('ds',$,'Pair 1600',$,$,$,$,$,.DOUBLE_DOOR_SINGLE_SWING.,.NOTDEFINED.,.T.,.F.)")
    x.add(f"IFCRELDEFINESBYTYPE('r2',$,$,$,({styled}),{style})")
    door("Fold", opening(wall, 6000, 1000, 0, 2100), op=".FOLDING_TO_RIGHT.")
    door("Turn", opening(wall, 7500, 1000, 0, 2100), op=".REVOLVING_RIGHT.")
    fill(opening(wall, 9000, 1200, 900, 1500), f"IFCWINDOWSTANDARDCASE('w1',$,'Fixed:1200 x 1500:345678',$,$,{x.place(rel=at)},$,'345678',$,$,.WINDOW.,.SINGLE_PANEL.,$)")
    fill(opening(wall, 11000, 1000, 900, 1200), f"IFCWINDOW('w2',$,'Tall',$,$,{x.place(rel=at)},$,'W2',{x.mm(2500)},{x.mm(1000)},.WINDOW.,.SINGLE_PANEL.,$)")
    # An opening with no body: the window's own body sizes it.
    empty = x.add(f"IFCOPENINGELEMENT('oe',$,'Opening',$,$,{x.place(rel=at)},$,$,.OPENING.)")
    x.add(f"IFCRELVOIDSELEMENT('ve',$,$,$,{wall},{empty})")
    own = x.shape(x.extrude(x.rect(800, 100, (13400, 0)), 600, at=(0, 0, 1500)))
    fill(empty, f"IFCWINDOW('w3',$,'Small',$,$,{x.place(rel=at)},{own},'W3',$,$,.WINDOW.,.SINGLE_PANEL.,$)")
    door("Overlap", opening(wall, 500, 900, 0, 2100), "'D9'", x.mm(2100), x.mm(900))
    door("Ghosted", opening(ghost, 500, 900, 0, 2100), "'D10'")
    x.product(f"IFCDOOR('loose',$,'Loose',$,$,{x.place(rel=at)},$,'D11',$,$,.DOOR.,$,$)", s)
    golden.check(imported(run, workdir, x.text()), "openings.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Property sets: project parameters and other programs' values.

def test_property_sets_become_project_parameters_of_their_kinds(run, workdir, golden):
    """CATCHES: a rewrite that reads property values otherwise: each single value a parameter of its kind (text from a
    label, identifier or text, yes or no from a boolean or logical true or false, a length in the file's unit made mm,
    a number from a real, integer, count or numeric measure), named less what a formula can't say, for the categories of
    what holds them; `Project Parameters` names kept whole; BIMCraft's own sets and `LoadBearing` not read twice; a
    structural program's names (V1, P1, L1) as their Marks unless they are only a type's; or a name a family's
    parameter has refused on components and said so."""
    x = Ifc(name="'Eberick'", units=("IFCSIUNIT(*,.LENGTHUNIT.,.CENTI.,.METRE.)",), unit_mm=10.0)
    s, at = x.storey()

    def product(cls, name, object_type, xyz, solid, last="$"):
        return x.product(f"{cls}('g{x.n}',$,'{name}',$,{object_type},{x.place(xyz, at)},{x.shape(solid)},$,{last})", s)

    def beam(name, object_type, xy, length=3000):
        solid = x.extrude(x.rect(140, 400, (0, 0)), length, at=(-length / 2, 0, -200), z=(1, 0, 0), xdir=(0, 1, 0))
        return product("IFCBEAM", name, object_type, (xy[0], xy[1], 3000), solid)

    def props(on, name, *values):
        made = [x.add(v) for v in values]
        pset = x.add(f"IFCPROPERTYSET('ps{x.n}',$,'{name}',$,({','.join(made)}))")
        x.add(f"IFCRELDEFINESBYPROPERTIES('rp{x.n}',$,$,$,({','.join(on)}),{pset})")

    v1 = beam("V1", "$", (0, 0))
    v1b = beam("V1", "$", (0, 4000))
    own = beam("Concrete 14 x 40", "'Concrete 14 x 40'", (0, 8000))
    p1 = product("IFCCOLUMN", "P1", "$", (5000, 0, 0), x.extrude(x.rect(200, 300), 3000))
    l1 = product("IFCSLAB", "L1", "$", (8000, 0, 0), x.extrude(x.rect(1000, 1000, (500, 500)), 150, at=(0, 0, -150)), ".FLOOR.")
    chair = product("IFCFURNISHINGELEMENT", "Stool:Low", "$", (12000, 0, 0), x.extrude(x.rect(300, 300), 450))
    props([v1, v1b], "AltoQi_Eberick_Padr\\S\\co",
          "IFCPROPERTYSINGLEVALUE('Cobrimento',$,IFCLENGTHMEASURE(3.),$)",
          "IFCPROPERTYSINGLEVALUE('Classe de concreto',$,IFCTEXT('C-25'),$)",
          "IFCPROPERTYSINGLEVALUE('Cargas de parede (G2)',$,IFCREAL(0.5),$)",
          "IFCPROPERTYSINGLEVALUE('Se\\S\\g\\S\\co_bw',$,IFCPOSITIVELENGTHMEASURE(14.),$)",
          "IFCPROPERTYSINGLEVALUE('Barras',$,IFCINTEGER(4),$)",
          "IFCPROPERTYSINGLEVALUE('Estribos',$,IFCCOUNTMEASURE(12.),$)",
          "IFCPROPERTYSINGLEVALUE('Fator',$,IFCNUMERICMEASURE(1.4),$)",
          "IFCPROPERTYSINGLEVALUE('Codigo',$,IFCIDENTIFIER('VX-1'),$)",
          "IFCPROPERTYSINGLEVALUE('Etiqueta',$,IFCLABEL('  trimmed  '),$)",
          "IFCPROPERTYSINGLEVALUE('Revisado',$,IFCBOOLEAN(.F.),$)",
          "IFCPROPERTYSINGLEVALUE('Aprovado',$,IFCLOGICAL(.T.),$)",
          "IFCPROPERTYSINGLEVALUE('Talvez',$,IFCLOGICAL(.U.),$)",
          "IFCPROPERTYSINGLEVALUE('Area',$,IFCAREAMEASURE(1.5),$)",
          "IFCPROPERTYSINGLEVALUE('Span',$,IFCLENGTHMEASURE('long'),$)",
          "IFCPROPERTYSINGLEVALUE('Ratio',$,IFCREAL($),$)",
          "IFCPROPERTYSINGLEVALUE('Nada',$,$,$)",
          "IFCPROPERTYSINGLEVALUE('(?)',$,IFCTEXT('x'),$)",
          "IFCPROPERTYSINGLEVALUE($,$,IFCTEXT('nameless'),$)",
          "IFCPROPERTYENUMERATEDVALUE('Status',$,(IFCLABEL('NEW')),$)")
    props([v1], "Pset_BeamCommon", "IFCPROPERTYSINGLEVALUE('Reference',$,IFCTEXT('Viga 14 X 40'),$)",
          "IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$)")
    props([p1, l1], "Project Parameters", "IFCPROPERTYSINGLEVALUE('Fire Rating',$,IFCTEXT('REI 60'),$)",
          "IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$)", "IFCPROPERTYSINGLEVALUE('Bad (name)',$,IFCTEXT('x'),$)")
    props([own], "BIMCraft_Whatever", "IFCPROPERTYSINGLEVALUE('Hidden',$,IFCTEXT('x'),$)")
    props([own], "RoomSeparation", "IFCPROPERTYSINGLEVALUE('Hidden too',$,IFCTEXT('x'),$)")
    props([chair], "Pset_Furniture", "IFCPROPERTYSINGLEVALUE('Height',$,IFCLENGTHMEASURE(45.),$)",
          "IFCPROPERTYSINGLEVALUE('Supplier',$,IFCTEXT('Acme'),$)")
    # The same name with another kind of value, and a value on what holds no parameters.
    props([p1], "Other", "IFCPROPERTYSINGLEVALUE('Cobrimento',$,IFCTEXT('three'),$)")
    props([x.storey("'Spare'", 6000)[0]], "Pset_Storey", "IFCPROPERTYSINGLEVALUE('Use',$,IFCTEXT('Plant'),$)")
    golden.check(imported(run, workdir, x.text()), "properties.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Reinforcing bars, masses and what BIMCraft has no element for.

def test_reinforcing_bars_by_their_swept_disks(run, workdir, golden):
    """CATCHES: a rewrite that reads a bar's path, diameter or grade wrongly, doesn't join disks that run end to end into
    one bent bar, keeps a bar whose disks are apart or of two radii, or one of a diameter BIMCraft has none of; or that
    loses the beam a bar is a part of."""
    x = Ifc(name="'Bars'", units=("IFCSIUNIT(*,.LENGTHUNIT.,.CENTI.,.METRE.)",), unit_mm=10.0)
    s, at = x.storey()
    solid = x.extrude(x.rect(200, 400, (0, 0)), 6000, at=(0, 0, 2800), z=(1, 0, 0), xdir=(0, 1, 0))
    beam = x.product(f"IFCBEAM('b',$,'Beam',$,$,{x.place(rel=at)},{x.shape(solid)},$,.BEAM.)", s)
    a, b, c, d = x.pt(0, 0, 0), x.pt(1000, 0, 0), x.pt(1000, 500, 0), x.pt(3000, 500, 0)
    lines = [x.add(f"IFCPOLYLINE(({p},{q}))") for p, q in ((a, b), (b, c), (d, c))]

    def bar(name, place, disks, grade="$", rel=None):
        items = [x.add(f"IFCSWEPTDISKSOLID({lines[k]},{x.mm(r)},$,$,$)") for k, r in disks]
        shape = x.shape(*items, kind="AdvancedSweptSolid")
        return x.add(f"IFCREINFORCINGBAR('{name}',$,'{name}',$,$,{place},{shape},$,{grade},12.,113.,150.,.NOTDEFINED.,.PLAIN.)")

    bars = [bar("Bent", x.place(rel=at), [(0, 6), (1, 6)], "'CA-60'"), bar("Apart", x.place(rel=at), [(0, 6), (2, 6)]),
            bar("Two radii", x.place(rel=at), [(0, 6), (1, 4)]), bar("Hair", x.place(rel=at), [(0, 1)]),
            bar("Box", x.place(rel=at), [], "' '")]
    s_contained = x.contained[s]
    s_contained.extend(bars)
    part = bar("Long", x.place((100, 0, 2650), at), [(0, 8)], "'CA-50'")
    x.add(f"IFCRELAGGREGATES('ag',$,$,$,{beam},({part}))")
    golden.check(imported(run, workdir, x.text(), inspect=False), "bars.txt")


def test_masses_and_what_bimcraft_has_no_element_for(run, workdir, golden):
    """CATCHES: a rewrite that doesn't read a proxy of object type `Mass` as a mass (its outline, base offset, top level or
    height, its name), keeps one whose outline changes up its height with no BIMCraft_Mass set to pair its corners, or
    one round a courtyard; or that doesn't list the rest of the building by class, counted, as BIMCraft has no element
    for it (and them)."""
    x = Ifc(name="'Masses'")
    s, at = x.storey()
    x.storey("'Top'", 9000)

    def mass(name, faces=None, solid=None):
        shape = x.shape(solid) if solid else x.shape(x.brep(faces), kind="Brep")
        return x.product(f"IFCBUILDINGELEMENTPROXY('m{x.n}',$,{name},$,'Mass',{x.place(rel=at)},{shape},$,.USERDEFINED.)", s)

    mass("'Block'", solid=x.extrude(x.ring([(0, 0), (6000, 0), (6000, 5000), (0, 5000)]), 9000, at=(0, 0, 0)))
    mass("$", solid=x.extrude(x.rect(4000, 4000, (20000, 2000)), 4200, at=(0, 0, 500)))
    top = [(31000, 1000, 5000), (35000, 1000, 5000), (35000, 4000, 5000), (31000, 4000, 5000)]
    bottom = [(30000, 0, 0), (30000, 5000, 0), (36000, 5000, 0), (36000, 0, 0)]
    sides = [[bottom[0], bottom[3], top[1], top[0]], [bottom[3], bottom[2], top[2], top[1]], [bottom[2], bottom[1], top[3], top[2]], [bottom[1], bottom[0], top[0], top[3]]]
    mass("'Taper'", faces=[top, bottom, *sides])
    court = x.add(f"IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,{x.polyline([(40000, 0), (50000, 0), (50000, 10000), (40000, 10000)], True)},({x.polyline([(44000, 4000), (44000, 6000), (46000, 6000), (46000, 4000)], True)}))")
    mass("'Ring'", solid=x.extrude(court, 3000))
    x.product(f"IFCBUILDINGELEMENTPROXY('m{x.n}',$,'Empty',$,'Mass',{x.place(rel=at)},$,$,.USERDEFINED.)", s)
    for cls in ["IFCMEMBER", "IFCMEMBER", "IFCPLATE", "IFCCURTAINWALL", "IFCFLOWTERMINAL"]:
        x.product(f"{cls}('o{x.n}',$,'{cls}',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(100, 100), 100))},$,$)", s)
    golden.check(imported(run, workdir, x.text(), inspect=False), "masses.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Stairs, ramps and railings another tool wrote.

def test_stairs_ramps_and_railings_measured_from_their_bodies(run, workdir, golden):
    """CATCHES: a rewrite that counts a stair's risers or measures its treads, width, start and way wrongly (from a stair
    of tread blocks, or a flight on its own with its own riser count and height), keeps one whose treads it can't find
    or whose flights differ; that reads a ramp's slope and foot wrongly from its flights' sloping tops or keeps a level
    one or one of flights of two slopes; or that runs a railing elsewhere (along its axis, else along the middle of a
    straight thin body at its top), sizes its height otherwise (its body, or the type it names), or keeps one with no
    axis that isn't straight, or no height."""
    x = Ifc(name="'Circulation'")
    s, at = x.storey()
    x.storey("'Above'", 1050)

    def blocks(x0, y0, n, tread=280, rise=175, width=1000, along_x=True):
        faces = []
        for k in range(n):
            if along_x:
                faces += box(x0 + k * tread, y0, 0, x0 + (k + 1) * tread, y0 + width, (k + 1) * rise)
            else:
                faces += box(x0, y0 + k * tread, 0, x0 + width, y0 + (k + 1) * tread, (k + 1) * rise)
        return x.shape(x.brep(faces), kind="Brep")

    x.product(f"IFCSTAIR('st1',$,'Blocks',$,$,{x.place(rel=at)},{blocks(0, 0, 5)},$,.STRAIGHT_RUN_STAIR.)", s)
    x.product(f"IFCSTAIRFLIGHT('st2',$,'Flight',$,$,{x.place(rel=at)},{blocks(5000, 0, 5, along_x=False)},$,6,5,{x.mm(175)},{x.mm(280)},.STRAIGHT.)", s)
    x.product(f"IFCSTAIR('st3',$,'Slab',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(1000, 3000, (10000, 1500)), 200))},$,.STRAIGHT_RUN_STAIR.)", s)
    odd = x.product(f"IFCSTAIR('st4',$,'Odd',$,$,{x.place(rel=at)},$,$,.TWO_STRAIGHT_RUN_STAIR.)", s)
    f1 = x.add(f"IFCSTAIRFLIGHT('f1',$,'Flight',$,$,{x.place(rel=at)},{blocks(15000, 0, 3)},$,$,$,$,$,.STRAIGHT.)")
    f2 = x.add(f"IFCSTAIRFLIGHT('f2',$,'Flight',$,$,{x.place(rel=at)},{blocks(15000, 2000, 3, width=1400)},$,$,$,$,$,.STRAIGHT.)")
    x.add(f"IFCRELAGGREGATES('ag1',$,$,$,{odd},({f1},{f2}))")
    x.product(f"IFCSTAIR('st5',$,'Ghost',$,$,{x.place(rel=at)},$,$,.STRAIGHT_RUN_STAIR.)", s)

    def sloped(x0, y0, length, width, rise, z0=0):
        top = [(x0, y0, z0), (x0 + length, y0, z0 + rise), (x0 + length, y0 + width, z0 + rise), (x0, y0 + width, z0)]
        under = [(p[0], p[1], z0 - 150) for p in reversed(top)]
        sides = [[(a[0], a[1], z0 - 150), (b[0], b[1], z0 - 150), b, a] for a, b in zip(top, top[1:] + top[:1])]
        return x.shape(x.brep([top, under, *sides]), kind="Brep")

    ramp = x.product(f"IFCRAMP('r1',$,'Ramp',$,$,{x.place(rel=at)},$,$,.STRAIGHT_RUN_RAMP.)", s)
    run1 = x.add(f"IFCRAMPFLIGHT('rf1',$,'Flight',$,$,{x.place(rel=at)},{sloped(20000, 0, 6000, 1200, 500)},$,.STRAIGHT.)")
    x.add(f"IFCRELAGGREGATES('ag2',$,$,$,{ramp},({run1}))")
    x.product(f"IFCRAMP('r2',$,'Flat',$,$,{x.place(rel=at)},{sloped(30000, 0, 6000, 1200, 0)},$,.STRAIGHT_RUN_RAMP.)", s)
    steep = x.product(f"IFCRAMP('r3',$,'Steep',$,$,{x.place(rel=at)},$,$,.TWO_STRAIGHT_RUN_RAMP.)", s)
    runs = [x.add(f"IFCRAMPFLIGHT('rf2',$,'Flight',$,$,{x.place(rel=at)},{sloped(40000, 0, 6000, 1200, 500)},$,.STRAIGHT.)"),
            x.add(f"IFCRAMPFLIGHT('rf3',$,'Flight',$,$,{x.place(rel=at)},{sloped(40000, 3000, 6000, 1200, 300, 500)},$,.STRAIGHT.)")]
    x.add(f"IFCRELAGGREGATES('ag3',$,$,$,{steep},({','.join(runs)}))")

    def railing(name, body=None, axis=None, object_type="$"):
        reps = []
        if body is not None:
            reps.append(x.add(f"IFCSHAPEREPRESENTATION($,'Body','SweptSolid',({body}))"))
        if axis is not None:
            reps.append(x.add(f"IFCSHAPEREPRESENTATION($,'Axis','Curve3D',({axis}))"))
        shape = x.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({','.join(reps)}))") if reps else "$"
        return x.product(f"IFCRAILING('{name}',$,'{name}',$,{object_type},{x.place(rel=at)},{shape},$,.GUARDRAIL.)", s)

    railing("Axis", x.extrude(x.rect(4000, 50, (2000, -2000)), 1000), x.polyline([(0, -2000, 1000), (4000, -2000, 1000), (4000, -5000, 1000)]))
    railing("Straight", x.extrude(x.rect(3000, 50, (1500, -8000)), 900, at=(0, 0, 100)))
    railing("Wide", x.extrude(x.rect(3000, 500, (1500, -10000)), 900))
    railing("Flat", axis=x.polyline([(0, -12000, 0), (3000, -12000, 0)]))
    railing("Typed", x.extrude(x.rect(3000, 50, (1500, -14000)), 1200), x.polyline([(0, -14000, 1200), (3000, -14000, 1200)]), "'Railing - 1000mm'")
    golden.check(imported(run, workdir, x.text()), "circulation.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Odd geometry: what a reader meets now and then, and how far it follows a file that points round in circles.

def test_odd_geometry_reads_or_is_left_out_with_why(run, workdir, golden):
    """CATCHES: a rewrite that misreads less common geometry (a block, a bounding box, a non-uniform scaling operator in
    3D and 2D, an operator of no known kind, a polycurve of no segments, a whole circle as a profile, a trimmed polyline,
    trims that are bare numbers, a face with no bounds, a mapped item with no representation, a degenerate face, a
    profile of more corners than a face is ear-cut for, a point or direction of one coordinate, an x axis along z, a
    placement of no known kind, an index that isn't a whole number, a disk swept along a segment of no length or of no
    radius, a run extruded westward), or follows curves, profiles or solids nested past what it reads, instead of
    leaving out what has no body, with why."""
    x = Ifc(name="'Odd'")
    s, at = x.storey()
    n = iter(range(1000))

    def put(cls, solid, kind="SweptSolid", last="$", place=None):
        k = next(n)
        where = place or x.place((k * 2000, 0, 0), at)
        return x.product(f"{cls}('o{k}',$,'{cls[3:].title()} {k}',$,$,{where},{x.shape(solid, kind=kind)},$,{last})", s)

    put("IFCCOLUMN", x.add(f"IFCBLOCK({x.axes((-200, -150, 0))},{x.mm(400)},{x.mm(300)},{x.mm(3000)})"), "CSG")
    put("IFCCOLUMN", x.add(f"IFCBOUNDINGBOX({x.pt(-150, -150, 0)},{x.mm(300)},{x.mm(300)},{x.mm(2500)})"), "BoundingBox")
    rep = x.add(f"IFCSHAPEREPRESENTATION($,'Body','SweptSolid',({x.extrude(x.rect(100, 100, (0, 0)), 100)}))")
    rmap = x.add(f"IFCREPRESENTATIONMAP({x.world},{rep})")
    stretch = x.add(f"IFCCARTESIANTRANSFORMATIONOPERATOR3DNONUNIFORM($,$,{x.origin},1.,$,2.,3.)")
    put("IFCBUILDINGELEMENTPROXY", x.add(f"IFCMAPPEDITEM({rmap},{stretch})"), "MappedRepresentation")
    put("IFCBUILDINGELEMENTPROXY", x.add(f"IFCMAPPEDITEM({rmap},{x.add('IFCCARTESIANTRANSFORMATIONOPERATOR($,$,' + x.origin + ',1.)')})"), "MappedRepresentation")
    put("IFCBUILDINGELEMENTPROXY", x.add(f"IFCMAPPEDITEM({x.add(f'IFCREPRESENTATIONMAP({x.world},$)')},{stretch})"), "MappedRepresentation")
    wide = x.add(f"IFCCARTESIANTRANSFORMATIONOPERATOR2DNONUNIFORM($,$,{x.pt(0, 0)},1.,3.)")
    put("IFCCOLUMN", x.extrude(x.add(f"IFCDERIVEDPROFILEDEF(.AREA.,$,{x.rect(100, 100)},{wide},$)"), 3000))
    circle = x.add(f"IFCCIRCLE({x.add(f'IFCAXIS2PLACEMENT2D({x.pt(0, 0)},$)')},{x.mm(200)})")
    put("IFCCOLUMN", x.extrude(x.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{circle})"), 3000))
    spline = x.add(f"IFCBSPLINECURVEWITHKNOTS(2,({x.pt(0, 0)},{x.pt(100, 0)},{x.pt(100, 100)}),.UNSPECIFIED.,.T.,.F.,(3,3),(0.,1.),.UNSPECIFIED.)")
    put("IFCCOLUMN", x.extrude(x.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{spline})"), 3000))
    put("IFCCOLUMN", x.extrude(x.add(f"IFCCOMPOSITEPROFILEDEF(.AREA.,$,({x.rect(100, 100)}),$)"), 3000))
    put("IFCCOLUMN", x.extrude(x.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{x.polyline([(0, 0), (100, 0)])})"), 3000))
    deep = x.polyline([(0, 0), (300, 0), (300, 300), (0, 300)], True)
    for _ in range(18):
        deep = x.add(f"IFCCOMPOSITECURVE(({x.add(f'IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{deep})')}),.F.)")
    put("IFCCOLUMN", x.extrude(x.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{deep})"), 3000))
    deep = x.rect(300, 300)
    for _ in range(18):
        deep = x.add(f"IFCDERIVEDPROFILEDEF(.AREA.,$,{deep},{x.add('IFCCARTESIANTRANSFORMATIONOPERATOR2D($,$,' + x.pt(0, 0) + ',1.)')},$)")
    put("IFCCOLUMN", x.extrude(deep, 3000))
    deep = x.extrude(x.rect(300, 300), 3000)
    for _ in range(18):
        deep = x.add(f"IFCBOOLEANRESULT(.UNION.,{deep},{deep})")
    put("IFCCOLUMN", deep, "CSG")
    import math
    many = [(300 * math.cos(2 * math.pi * k / 70), 300 * math.sin(2 * math.pi * k / 70)) for k in range(70)]
    put("IFCBUILDINGELEMENTPROXY", x.extrude(x.ring(many), 500))
    faces = box(0, 0, 0, 400, 400, 400) + [[(0, 0, 0), (100, 0, 0), (200, 0, 0)]]
    made = []
    for face in faces:
        loop = x.add(f"IFCPOLYLOOP(({','.join(x.pt(*p) for p in face)}))")
        made.append(x.add(f"IFCFACE(({x.add(f'IFCFACEOUTERBOUND({loop},.T.)')}))"))
    made.append(x.add("IFCFACE(())"))
    put("IFCBUILDINGELEMENTPROXY", x.add(f"IFCFACETEDBREP({x.add(f'IFCCLOSEDSHELL(({chr(44).join(made)}))')})"), "Brep")
    pts = x.add(f"IFCCARTESIANPOINTLIST3D((({x.mm(0)},0.,0.),({x.mm(300)},0.,0.),(0.,{x.mm(300)},0.),(0.,0.,{x.mm(300)})))")
    put("IFCBUILDINGELEMENTPROXY", x.add(f"IFCTRIANGULATEDFACESET({pts},$,.T.,((1,3,2),(1,2,4),(1,4,3),(2,3,4),(1,2.5,3)),$)"), "Tessellation")
    lonely = x.add("IFCCARTESIANPOINT((5.))")
    column = x.extrude(x.rect(300, 300), 3000)
    put("IFCCOLUMN", column, place=x.add(f"IFCLOCALPLACEMENT({at},{x.add(f'IFCAXIS2PLACEMENT3D({lonely},$,$)')})"))
    put("IFCCOLUMN", column, place=x.add(f"IFCLOCALPLACEMENT({at},{x.add(f'IFCAXIS2PLACEMENT3D({x.pt(40000, 0, 0)},{x.dir(0, 0, 1)},{x.dir(0, 0, 1)})')})"))
    put("IFCCOLUMN", column, place=x.add(f"IFCLOCALPLACEMENT({at},{x.add(f'IFCAXIS1PLACEMENT({x.pt(42000, 0, 0)},$)')})"))
    put("IFCCOLUMN", column, place=x.add(f"IFCLOCALPLACEMENT({at},{x.add(f'IFCAXIS2PLACEMENT3D({x.pt(44000, 0, 0)},{x.add(chr(73) + 'FCDIRECTION((1.))')},$)')})"))
    westward = x.extrude(x.rect(200, 400), 3000, at=(0, 0, 2800), z=(-1, 0, 0), xdir=(0, 1, 0))
    put("IFCBEAM", westward, last=".BEAM.")
    line = x.polyline([(0, 0, 500), (2000, 0, 500), (2000, 0, 500), (2000, 2000, 500)])
    put("IFCPIPESEGMENT", x.add(f"IFCSWEPTDISKSOLID({line},{x.mm(25)},$,$,$)"), "AdvancedSweptSolid", ".RIGIDSEGMENT.")
    put("IFCPIPESEGMENT", x.add(f"IFCSWEPTDISKSOLID({line},0.,$,$,$)"), "AdvancedSweptSolid", ".RIGIDSEGMENT.")
    put("IFCPIPESEGMENT", x.add(f"IFCBOUNDINGBOX({x.pt(0, 0, 0)},0.,0.,0.)"), "BoundingBox", ".RIGIDSEGMENT.")
    sheet = [(0, 0, 0), (300, 0, 0), (300, 0, 3000), (0, 0, 3000)]
    loop = x.add(f"IFCPOLYLOOP(({','.join(x.pt(*p) for p in sheet)}))")
    flat = x.add(f"IFCFACEBASEDSURFACEMODEL(({x.add(chr(73) + 'FCCONNECTEDFACESET((' + x.add('IFCFACE((' + x.add('IFCFACEOUTERBOUND(' + loop + ',.T.)') + '))') + '))')}))")
    put("IFCCOLUMN", flat, "SurfaceModel")
    put("IFCCOLUMN", x.add(f"IFCSPHERE({x.axes()},{x.mm(500)})"), "CSG")
    put("IFCCOLUMN", x.add(f"IFCBLOCK({x.axes()},{x.mm(400)},$,{x.mm(3000)})"), "CSG")
    golden.check(imported(run, workdir, x.text(), inspect=False), "odd_geometry.txt")


def test_odd_walls_slabs_roofs_stairs_and_doors(run, workdir, golden):
    """CATCHES: a rewrite that misreads less common walls (an axis of an indexed polycurve with no segments, a trimmed
    polyline, trims of bare numbers, a curved axis with no body, a wall too long for the model taking its door with it),
    a stepped slab top, a shed roof over a triangle, an L or of two slabs in one plane, a roof of two pitches as one
    profile swept across and with a hole through it as a shaped one, a stair whose flight descends
    along its own axis, one with no treads, flights turning back to the right or by 45 degrees; or a door with no body
    anywhere or typed by something that isn't a door type."""
    x = Ifc(name="'Odd elements'")
    s, at = x.storey()
    x.storey("'Above'", 3000)

    def wall(name, y, axis, length=4000):
        body = x.extrude(x.rect(length, 200, (length / 2, y)), 3000)
        return x.product(f"IFCWALL('{name}',$,'{name}',$,$,{x.place(rel=at)},{x.shape(body, axis=axis)},$,$)", s)

    points = x.add(f"IFCCARTESIANPOINTLIST2D((({x.mm(0)},{x.mm(0)}),({x.mm(4000)},{x.mm(0)})))")
    wall("Indexed", 0, x.add(f"IFCINDEXEDPOLYCURVE({points},$,$)"))
    basis = x.polyline([(0, 3000), (4000, 3000)])
    wall("Trimmed", 3000, x.add(f"IFCTRIMMEDCURVE({basis},({x.pt(0, 3000)}),({x.pt(4000, 3000)}),.T.,.CARTESIAN.)"))
    wall("Bare trims", 6000, x.add(f"IFCTRIMMEDCURVE({x.polyline([(0, 6000), (4000, 6000)])},(0.),(1.),.T.,.PARAMETER.)"))
    circle = x.add(f"IFCCIRCLE({x.add(f'IFCAXIS2PLACEMENT2D({x.pt(0, 20000)},$)')},{x.mm(3000)})")
    arc = x.add(f"IFCTRIMMEDCURVE({circle},(IFCPARAMETERVALUE(0.)),(IFCPARAMETERVALUE(1.5707963267948966)),.T.,.PARAMETER.)")
    x.product(f"IFCWALL('Bent',$,'Bent',$,$,{x.place(rel=at)},{x.add(f'IFCPRODUCTDEFINITIONSHAPE($,$,({x.add(chr(73) + chr(70) + chr(67) + chr(83) + chr(72) + chr(65) + chr(80) + chr(69) + chr(82) + chr(69) + chr(80) + chr(82) + chr(69) + chr(83) + chr(69) + chr(78) + chr(84) + chr(65) + chr(84) + chr(73) + chr(79) + chr(78) + "($,'Axis','Curve2D',(" + arc + "))")}))')},$,$)", s)
    far = wall("Endless", 9000, x.polyline([(0, 9000), (2.5e9, 9000)]), length=2.5e9)
    hole = x.add(f"IFCOPENINGELEMENT('h1',$,'Opening',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(900, 400, (1450, 9000)), 2100))},$,.OPENING.)")
    x.add(f"IFCRELVOIDSELEMENT('v1',$,$,$,{far},{hole})")
    door = x.product(f"IFCDOOR('d1',$,'Far door',$,$,{x.place(rel=at)},$,'F1',$,$,.DOOR.,$,$)", s)
    x.add(f"IFCRELFILLSELEMENT('f1',$,$,$,{hole},{door})")
    host = wall("Host", 12000, x.polyline([(0, 12000), (8000, 12000)]), length=8000)
    for k, (name, typed) in enumerate([("Bodiless", None), ("Odd type", "IFCWINDOWTYPE('wt',$,'Window type',$,$,$,$,$,$,.WINDOW.,.SINGLE_PANEL.,.T.,$)")]):
        body = x.shape(x.extrude(x.rect(900, 400, (1000 + 3000 * k, 12000)), 2100)) if typed else "$"
        o = x.add(f"IFCOPENINGELEMENT('h{k + 2}',$,'Opening',$,$,{x.place(rel=at)},{body},$,.OPENING.)")
        x.add(f"IFCRELVOIDSELEMENT('v{k + 2}',$,$,$,{host},{o})")
        d = x.product(f"IFCDOOR('d{k + 2}',$,'{name}',$,$,{x.place(rel=at)},$,$,$,$,.DOOR.,$,$)", s)
        x.add(f"IFCRELFILLSELEMENT('f{k + 2}',$,$,$,{o},{d})")
        if typed:
            x.add(f"IFCRELDEFINESBYTYPE('t{k}',$,$,$,({d}),{x.add(typed)})")
    # A slab stepped 100 mm halfway along.
    step = x.add(f"IFCBOOLEANRESULT(.UNION.,{x.extrude(x.rect(2000, 2000, (1000, 1000)), 200, at=(0, 0, -200))},{x.extrude(x.rect(2000, 2000, (3000, 1000)), 200, at=(0, 0, -300))})")
    x.product(f"IFCSLAB('sl',$,'Stepped',$,$,{x.place((20000, 0, 0), at)},{x.shape(step, kind='CSG')},$,.FLOOR.)", s)

    def slope(corners, rise, z0=3000, t=200):
        top = [(p[0], p[1], z0 + rise(p)) for p in corners]
        under = [(p[0], p[1], p[2] - t) for p in reversed(top)]
        sides = [[(a[0], a[1], a[2] - t), (b[0], b[1], b[2] - t), b, a] for a, b in zip(top, top[1:] + top[:1])]
        return [top, under, *sides]

    triangle = slope([(30000, 0), (36000, 0), (30000, 6000)], lambda p: (p[1]) / 4)
    x.product(f"IFCROOF('r1',$,'Triangle',$,$,{x.place(rel=at)},{x.shape(x.brep(triangle), kind='Brep')},$,.SHED_ROOF.)", s)
    roof = x.product(f"IFCROOF('r2',$,'Two in a row',$,$,{x.place(rel=at)},$,$,.SHED_ROOF.)", s)
    halves = []
    for k in range(2):
        rect = [(40000 + 3000 * k, 0), (43000 + 3000 * k, 0), (43000 + 3000 * k, 4000), (40000 + 3000 * k, 4000)]
        part = x.add(f"IFCSLAB('rs{k}',$,'Roof slab',$,$,{x.place(rel=at)},{x.shape(x.brep(slope(rect, lambda p: p[1] / 4)), kind='Brep')},$,.ROOF.)")
        halves.append(part)
    x.add(f"IFCRELAGGREGATES('ra',$,$,$,{roof},({','.join(halves)}))")

    def blocks(x0, y0, n, tread=280, rise=175, width=1000, down=False, along_y=False):
        faces = []
        for k in range(n):
            z = (n - k if down else k + 1) * rise
            if along_y:
                faces += box(x0, y0 + k * tread, 0, x0 + width, y0 + (k + 1) * tread, z)
            else:
                faces += box(x0 + k * tread, y0, 0, x0 + (k + 1) * tread, y0 + width, z)
        return x.shape(x.brep(faces), kind="Brep")

    x.product(f"IFCSTAIRFLIGHT('sf1',$,'Down',$,$,{x.place(rel=at)},{blocks(50000, 0, 4, down=True)},$,$,$,$,$,.STRAIGHT.)", s)
    x.product(f"IFCSTAIRFLIGHT('sf2',$,'Flat',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(1000, 3000, (56000, 1500)), 0.5))},$,$,$,$,$,.STRAIGHT.)", s)
    back = x.product(f"IFCSTAIR('sb',$,'Back right',$,$,{x.place(rel=at)},$,$,.HALF_TURN_STAIR.)", s)
    up = x.add(f"IFCSTAIRFLIGHT('b1',$,'Up',$,$,{x.place(rel=at)},{blocks(60000, 0, 3)},$,$,$,$,$,.STRAIGHT.)")
    down_place = x.place((60000 + 840, -1100, 0), at, x=(-1, 0, 0))
    faces = []
    for k in range(3):
        faces += box(k * 280, -1000, 0, (k + 1) * 280, 0, 525 + (k + 1) * 175)
    x.add(f"IFCRELAGGREGATES('ba',$,$,$,{back},({up},{x.add(f'IFCSTAIRFLIGHT(' + chr(39) + 'b2' + chr(39) + ',$,' + chr(39) + 'Return' + chr(39) + ',$,$,' + down_place + ',' + x.shape(x.brep(faces), kind='Brep') + ',$,$,$,$,$,.STRAIGHT.)')}))")
    slant = x.product(f"IFCSTAIR('sk',$,'Slant',$,$,{x.place(rel=at)},$,$,.NOTDEFINED.)", s)
    one = x.add(f"IFCSTAIRFLIGHT('k1',$,'One',$,$,{x.place(rel=at)},{blocks(70000, 0, 3)},$,$,$,$,$,.STRAIGHT.)")
    turned = x.place((70000 + 1500, 0, 0), at, x=(0.7071067811865476, 0.7071067811865476, 0))
    faces = []
    for k in range(3):
        faces += box(k * 280, 0, 0, (k + 1) * 280, 1000, 525 + (k + 1) * 175)
    two = x.add(f"IFCSTAIRFLIGHT('k2',$,'Two',$,$,{turned},{x.shape(x.brep(faces), kind='Brep')},$,$,$,$,$,.STRAIGHT.)")
    x.add(f"IFCRELAGGREGATES('ka',$,$,$,{slant},({one},{two}))")
    # A shed roof over an L, one plane sloping north (read as a roof by footprint, its high edges upright gables).
    ell = [(80000, 0), (86000, 0), (86000, 3000), (83000, 3000), (83000, 6000), (80000, 6000)]
    x.product(f"IFCROOF('r3',$,'Ell',$,$,{x.place(rel=at)},{x.shape(x.brep(slope(ell, lambda p: p[1] / 4)), kind='Brep')},$,.SHED_ROOF.)", s)
    # A roof of two slopes of different pitch, the steeper written as two slabs in one plane (read as one profile swept
    # across, the two slabs one stretch of it); and the same with a hole through its shallow side (read as a flat roof
    # shaped to its top, the hole a courtyard).
    def asymmetric(x0, hole):
        def top(p):
            return 3000 + (p[0] - x0) / 2 if p[0] <= x0 + 4000 else 5000 - (p[0] - x0 - 4000) / 4

        pieces = [[(x0, 0), (x0 + 2000, 0), (x0 + 2000, 5000), (x0, 5000)], [(x0 + 2000, 0), (x0 + 4000, 0), (x0 + 4000, 5000), (x0 + 2000, 5000)]]
        if hole:
            pieces += [[(x0 + 4000, 0), (x0 + 6000, 0), (x0 + 6000, 5000), (x0 + 4000, 5000)], [(x0 + 7000, 0), (x0 + 12000, 0), (x0 + 12000, 5000), (x0 + 7000, 5000)],
                       [(x0 + 6000, 0), (x0 + 7000, 0), (x0 + 7000, 2000), (x0 + 6000, 2000)], [(x0 + 6000, 3000), (x0 + 7000, 3000), (x0 + 7000, 5000), (x0 + 6000, 5000)]]
        else:
            pieces += [[(x0 + 4000, 0), (x0 + 12000, 0), (x0 + 12000, 5000), (x0 + 4000, 5000)]]
        faces = []
        for piece in pieces:
            steep = piece[0][0] < x0 + 4000
            # 10 mm thick square to each slope, plumb as much more as its pitch makes it.
            drop = 10 * (1.25 ** 0.5 if steep else (1 + 1 / 16) ** 0.5)
            up = [(p[0], p[1], top(p)) for p in piece]
            faces += [up, [(p[0], p[1], p[2] - drop) for p in reversed(up)]]
        return x.shape(x.brep(faces), kind="Brep")

    x.product(f"IFCROOF('r4',$,'Asymmetric',$,$,{x.place(rel=at)},{asymmetric(100000, False)},$,.GABLE_ROOF.)", s)
    x.product(f"IFCROOF('r5',$,'Holed',$,$,{x.place(rel=at)},{asymmetric(120000, True)},$,.GABLE_ROOF.)", s)
    # A column in an assembly nine deep, in no storey: on the level it stands on.
    deep = x.add(f"IFCCOLUMN('dc',$,'Deep',$,$,{x.place((90000, 0, 3000), at)},{x.shape(x.extrude(x.rect(300, 300), 2500))},$,$)")
    for k in range(9):
        whole = x.add(f"IFCELEMENTASSEMBLY('as{k}',$,'Assembly',$,$,{x.place(rel=at)},$,$,.NOTDEFINED.,.NOTDEFINED.)")
        x.add(f"IFCRELAGGREGATES('ag{k}',$,$,$,{whole},({deep}))")
        deep = whole
    x.contained[s].append(deep)
    golden.check(imported(run, workdir, x.text(), inspect=False), "odd_elements.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Phases and design options from the property sets BIMCraft writes, and what a file may break of them.

PHASED = r"""wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}
phase {"name": "Demolition", "before": "New Construction"}
option {"set": "Facade", "options": ["Brick", "Glass"]}
phase_filter {"name": "Renovation", "new": "overridden", "temporary": "not-displayed"}
phase {"overrides": {"new": {"cut": {"color": [0, 0, 200]}}}}
modify {"id": 100003, "params": {"Phase Created": "New Construction"}}
modify {"id": 100004, "params": {"Phase Created": "Demolition", "Phase Demolished": "New Construction"}}
modify {"id": 100005, "params": {"Design Option": "Facade: Glass"}}
"""


def phased_ifc(run, workdir):
    """The IFC BIMCraft writes of a house with a wall made in a later phase, one made then and taken down in another, one
    in an option, and the project's own phase filter and overrides."""
    (workdir / "phased.txt").write_text(PHASED)
    make_project(run, workdir, "phased.bimcraft", ["--script", "phased.txt"])
    assert run(["convert", "phased.bimcraft", "phased.ifc"]).returncode == 0
    return (workdir / "phased.ifc").read_text(encoding="utf-8")


def text_value(name, value):
    return f"IFCPROPERTYSINGLEVALUE('{name}',$,IFCTEXT('{value}'),$)"


TAMPERED = {
    "as_written": ("", ""),
    "unknown_phase": (text_value("Phase Created", "New Construction"), text_value("Phase Created", "Nowhere")),
    "demolished_before_made": (text_value("Phase Demolished", "New Construction"), text_value("Phase Demolished", "Existing")),
    "unknown_option": (text_value("Design Option", "Facade: Glass"), text_value("Design Option", "Roof: Gable")),
    "phases_twice": ("IFCTEXT('Existing'),IFCTEXT('Demolition')", "IFCTEXT('Existing'),IFCTEXT('Existing')"),
    "phase_that_is_no_name": ("IFCTEXT('Existing'),IFCTEXT('Demolition')", "IFCTEXT('Existing'),IFCINTEGER(7)"),
    "option_sets_not_json": ('{"Facade":', '{"Facade'),
    "primary_not_an_option": ('"primary":"Brick"', '"primary":"Nope"'),
    "filter_of_no_kind": ('"temporary":"not-displayed"', '"temporary":"gone"'),
    "override_colour_out_of_range": ("[0,0,200]", "[0,0,999]"),
    "phase_created_said_implied": (text_value("Phase Created", "New Construction"),
                                   "IFCPROPERTYSINGLEVALUE('Phase Created','Implied: no phase is set for it, so it was made in the first phase',IFCTEXT('New Construction'),$)"),
    "phase_created_not_text": (text_value("Phase Created", "New Construction"), "IFCPROPERTYSINGLEVALUE('Phase Created',$,IFCINTEGER(7),$)"),
    "phases_not_a_list": ("IFCPROPERTYLISTVALUE('Phases',$,(IFCTEXT('Existing'),IFCTEXT('Demolition'),IFCTEXT('New Construction')),$)",
                          "IFCPROPERTYLISTVALUE('Phases',$,IFCTEXT('Existing'),$)"),
    "a_set_another_tool_calls_its_own": ("'BIMCraft_Phasing'", "'Phasing'"),
    "project_set_without_phases": ("IFCPROPERTYLISTVALUE('Phases'", "IFCPROPERTYLISTVALUE('Old Phases'"),
    "project_set_of_phases_alone": [("'Phase Filters'", "'Old Filters'"), ("'Design Option Sets'", "'Old Sets'"), ("'Phase Overrides'", "'Old Overrides'")],
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
def test_phases_and_options_come_back_and_what_breaks_a_rule_is_left_out(run, workdir, golden, case):
    """CATCHES: a rewrite that doesn't bring the project's phases (in order), phase filters, overrides and design option
    sets back from BIMCraft_Phasing, or each element's phase and option from its own; or that, where the file breaks a
    rule (a phase or option the project hasn't, a demolition before the making, phases twice or not names, JSON that
    doesn't read, a primary that's no option, a filter or override out of range), refuses the file or loses the
    element instead of leaving that value out and saying so; or that reads another tool's set of another name."""
    text = phased_ifc(run, workdir)
    changes = TAMPERED[case]
    for was, now in changes if isinstance(changes, list) else [changes]:
        assert was in text
        text = text.replace(was, now, 1)
    golden.check(imported(run, workdir, text), f"phased_{case}.txt")


def test_a_phase_on_what_holds_no_parameters_is_passed_over(run, workdir, golden):
    """CATCHES: a rewrite that gives a storey or a grid a phase from a BIMCraft_Phasing set, or refuses the file, instead
    of reading the set only onto what holds parameters."""
    x = Ifc(name="'Phases'")
    s, at = x.storey()
    wall = x.product(f"IFCWALL('w',$,'Wall',$,$,{x.place(rel=at)},{x.shape(x.extrude(x.rect(4000, 200, (2000, 0)), 3000))},$,$)", s)
    axis = x.add(f"IFCGRIDAXIS('1',{x.polyline([(0, -1000), (0, 5000)])},.T.)")
    grid = x.product(f"IFCGRID('g',$,'Grid',$,$,{x.place(rel=at)},$,({axis}),(),$)", s)
    made = x.add("IFCPROPERTYSINGLEVALUE('Phase Created',$,IFCTEXT('New Construction'),$)")
    pset = x.add(f"IFCPROPERTYSET('ps',$,'BIMCraft_Phasing',$,({made}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({wall},{grid},{s}),{pset})")
    golden.check(imported(run, workdir, x.text(), inspect=False), "phase_on_a_grid.txt")


def test_a_shaped_floor_over_layers_none_says_tapers_guesses_which_does(run, workdir, golden):
    """CATCHES: a rewrite that reads a shaped slab whose underside is level, over layers none of which is marked
    variable, without marking the one that takes up the fall (insulation, else the substrate)."""
    script = r"""type {"category": "floor", "name": "Terrace", "layers": [{"function": "finish", "thickness": 10}, {"function": "substrate", "thickness": 60, "variable": true}, {"function": "structure", "thickness": 200}]}
floor {"boundary": [[0,0],[8000,0],[8000,6000],[0,6000]], "type": "Terrace"}
edit_shape {"id": 100002, "points": [{"at": [4000,3000], "z": -30}]}
type {"category": "floor", "name": "Warm", "layers": [{"function": "finish", "thickness": 10}, {"function": "thermal", "thickness": 60, "variable": true}, {"function": "structure", "thickness": 200}]}
floor {"boundary": [[10000,0],[18000,0],[18000,6000],[10000,6000]], "type": "Warm"}
edit_shape {"id": 100003, "points": [{"at": [14000,3000], "z": -30}]}
"""
    (workdir / "shaped.txt").write_text(script)
    make_project(run, workdir, "shaped.bimcraft", ["--script", "shaped.txt"])
    assert run(["convert", "shaped.bimcraft", "shaped.ifc"]).returncode == 0
    text = (workdir / "shaped.ifc").read_text(encoding="utf-8")
    assert text.count("'Variable'") == 2
    golden.check(imported(run, workdir, text.replace("'Variable'", "$")), "shaped_guessed.txt")


# ---------------------------------------------------------------------------------------------------------------------
# Limits, and files with parts missing.

def test_a_file_with_no_storey_gets_a_level_and_broken_relations_are_passed_over(run, workdir, golden):
    """CATCHES: a rewrite that makes no level for a file with no storey (BIMCraft's `Level 1` at 0), puts its elements
    elsewhere, or trips over relationships that point at nothing or hold no list; or that misreads a nanometre length
    unit or a unit assignment holding something that isn't a unit."""
    x = Ifc(name="$", units=("IFCSIUNIT(*,.LENGTHUNIT.,.NANO.,.METRE.)", "IFCDERIVEDUNIT((),.USERDEFINED.,'thing')"), unit_mm=1e-6)
    wall = x.add(f"IFCWALL('w',$,'Wall',$,$,{x.place()},{x.shape(x.extrude(x.rect(4000, 200, (2000, 0)), 2500))},$,$)")
    x.add(f"IFCSLAB('f',$,'Slab',$,$,{x.place()},{x.shape(x.extrude(x.rect(4000, 3000, (2000, 1500)), 200, at=(0, 0, -200)))},$,.FLOOR.)")
    for rel in ["IFCRELCONTAINEDINSPATIALSTRUCTURE('a',$,$,$,(#99999),$)", "IFCRELAGGREGATES('b',$,$,$,$,(#99999))",
                f"IFCRELVOIDSELEMENT('c',$,$,$,{wall},$)", "IFCRELFILLSELEMENT('d',$,$,$,$,$)",
                f"IFCRELDEFINESBYTYPE('e',$,$,$,({wall}),$)", f"IFCRELDEFINESBYTYPE('e2',$,$,$,({wall}),#99999)",
                f"IFCRELASSOCIATESMATERIAL('f',$,$,$,({wall}),$)", f"IFCRELASSIGNSTOGROUP('g',$,$,$,({wall}),$,$)",
                f"IFCRELDEFINESBYPROPERTIES('h',$,$,$,({wall}),#99999)", "IFCRELDEFINESBYPROPERTIES('i',$,$,$,$,$)"]:
        x.add(rel)
    golden.check(imported(run, workdir, x.text(), inspect=False, name="no storey.ifc"), "no_storey.txt")


def test_what_passes_the_limits_of_a_project_is_left_out_with_why(run, workdir, golden):
    """CATCHES: a rewrite that makes more project parameters than a project holds, a room separation line or a bar of
    more segments than one may have, or a swept disk of more segments than BIMCraft builds, instead of leaving out what
    passes the limit and saying so; or keeps a layer set of more layers than a type holds, or one whose usage or set is
    no layer set."""
    x = Ifc(name="'Limits'")
    s, at = x.storey()

    def wall(name, y):
        body = x.shape(x.extrude(x.rect(4000, 330, (2000, y)), 3000), axis=x.polyline([(0, y), (4000, y)]))
        return x.product(f"IFCWALL('{name}',$,'{name}',$,$,{x.place(rel=at)},{body},$,$)", s)

    many = wall("Many", 0)
    props = [x.add(f"IFCPROPERTYSINGLEVALUE('P{k}',$,IFCREAL(1.),$)") for k in range(260)]
    pset = x.add(f"IFCPROPERTYSET('ps',$,'Project Parameters',$,({','.join(props)}))")
    x.add(f"IFCRELDEFINESBYPROPERTIES('rp',$,$,$,({many}),{pset})")
    concrete = x.add("IFCMATERIAL('Concrete',$,$)")
    thick = [x.add(f"IFCMATERIALLAYER({concrete},{x.mm(10)},$,$,$,$,$)") for _ in range(33)]
    x.add(f"IFCRELASSOCIATESMATERIAL('m1',$,$,$,({wall('Layered 33', 2000)}),{x.add(f'IFCMATERIALLAYERSET(({chr(44).join(thick)}),' + chr(39) + '33' + chr(39) + ',$)')})")
    x.add(f"IFCRELASSOCIATESMATERIAL('m2',$,$,$,({wall('Usage of nothing', 4000)}),{x.add('IFCMATERIALLAYERSETUSAGE($,.AXIS2.,.NEGATIVE.,0.,$)')})")
    x.add(f"IFCRELASSOCIATESMATERIAL('m3',$,$,$,({wall('Plain material', 6000)}),{concrete})")
    listed = x.add(f"IFCMATERIALLIST(({concrete}))")
    x.add(f"IFCRELASSOCIATESMATERIAL('m4',$,$,$,({wall('Material list', 8000)}),{listed})")
    n = 10002
    coords = ",".join(f"({k * 100}.,0.,0.)" for k in range(n))
    index = ",".join(str(k + 1) for k in range(n))
    line = x.add(f"IFCINDEXEDPOLYCURVE({x.add(f'IFCCARTESIANPOINTLIST3D(({coords}))')},(IFCLINEINDEX(({index}))),$)")
    x.product(f"IFCVIRTUALELEMENT('v',$,'Room Separation Line',$,'RoomSeparation',{x.place((0, 20000, 0), at)},{x.shape(line, ident='Axis', kind='Curve2D')},$)", s)
    disk = x.add(f"IFCSWEPTDISKSOLID({line},{x.mm(5)},$,$,$)")
    x.product(f"IFCCABLESEGMENT('k',$,'Long cable',$,$,{x.place((0, 30000, 2000), at)},{x.shape(disk, kind='AdvancedSweptSolid')},$,.CABLESEGMENT.)", s)
    x.product(f"IFCREINFORCINGBAR('b',$,'Long bar',$,$,{x.place((0, 40000, 0), at)},{x.shape(disk, kind='AdvancedSweptSolid')},$,$,10.,78.5,1000.,.NOTDEFINED.,.PLAIN.)", s)
    (workdir / "limits.ifc").write_text(x.text())
    r = run(["run", "limits.ifc", "--cmd", 'elements {"category": "wall"}', "--cmd", 'elements {"category": "roomseparator", "limit": 1}'])
    golden.check_run(r, "limits.txt")
