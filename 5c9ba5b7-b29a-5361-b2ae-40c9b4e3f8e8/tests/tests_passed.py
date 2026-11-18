"""Reward Kit criterion: the fraction of the active hidden tests the submission passed (0 for a disqualified one).

Read from the hidden-test evaluator's summary, which tests/test.sh writes before rewardkit runs."""

import json
from pathlib import Path

from rewardkit import criteria, criterion

SUMMARY = Path("/logs/verifier/test_summary.json")


@criterion(description="fraction of the active hidden tests passed (0 for a disqualified submission)")
def pass_rate(workspace: Path) -> float:
    summary = json.loads(SUMMARY.read_text())
    return 0.0 if summary.get("disqualified") else float(summary["reward"])


criteria.pass_rate()
