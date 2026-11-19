"""Shared checking for the `test_hard_edge_*` modules.

Each case is a `run_case` dict (see conftest.py). The whole transcript, every file the
case lists under `outputs`, and (when `listing` is true) the sorted listing of the
working directory afterwards are compared with goldens captured from the reference
binary under eval/test_resources/<module>/.
"""

from conftest import case_transcript, golden_name, listing, read_golden, run_case


def expect(test_file: str, name: str, actual: str) -> None:
    """Compare `actual` with the golden `<name>.golden` of the calling test module."""
    assert actual == read_golden(test_file, name)


def check(run, workdir, case: dict, test_file: str):
    proc, written = run_case(run, workdir, case)
    expect(test_file, golden_name(case["id"]), case_transcript(proc, case, workdir))
    for rel, text in written.items():
        expect(test_file, golden_name(case["id"], rel), text)
    if case.get("listing"):
        expect(test_file, golden_name(case["id"]) + "__listing", listing(workdir))
    return proc
