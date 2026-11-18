# Binary inputs of test_imports.py

All synthetic, written for this suite; no Autodesk content.

- `*.rvt`, `*.rfa`, `*.rft`: Revit-shaped Compound Files written by the program's own fixture writer
  (`crates/rvt/src/project_fixture.rs` and `fixture.rs`, Apache-2.0, the `testing` feature) from a scratch copy of the crate
  outside the repository, using its test helpers (walls, floors, roofs, openings, columns, rooms, pipes, ducts, boxes).
- `room.dwg`: the dwg crate's `room_dxf()` test drawing written as DWG by acadrust 0.6.6 (MPL-2.0, unmodified) through
  `bimcraft_dwg::dwg_from_dxf` (the `testing` feature), in the same scratch build.
