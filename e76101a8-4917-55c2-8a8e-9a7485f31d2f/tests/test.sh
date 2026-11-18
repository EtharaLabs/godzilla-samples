#!/usr/bin/env bash
# Offline verifier. The hidden tests run first; Harbor Reward Kit then writes /logs/verifier/reward.json from their
# results (tests/tests_passed.py, tests/reward.toml). The rubric (tests/test_output.py, tests/judge.toml) is scored
# after the run.
set -uo pipefail
cd /  # Harbor starts this in /workspace, the submission's
mkdir -p /logs/verifier
# Harbor hands the verifier /logs/verifier world-writable (0777), and the build and the hidden tests run as the agent
# user: before any of their code runs, it becomes root's, so nothing in it is theirs to plant, link or replace
# (delivery QC review, 2026-11-11: a planted reward.json, kept when the evaluator was made to fail, scored 1.0).
chown root:root /logs/verifier && chmod 0755 /logs/verifier || exit 1
echo 0 > /logs/verifier/reward.txt  # fail closed: the reward is 0 until the grading has written one
# Whatever stops this script, a reward is left: reward.json (what Harbor reads first) and reward.txt with the same
# value (what other runners read); a missing one is 0.
fail_closed() {
  mkdir -p /logs/verifier
  [ -s /logs/verifier/reward.json ] || printf '{"reward": 0.0}' > /logs/verifier/reward.json
  python3 -I -c 'import json; print(json.load(open("/logs/verifier/reward.json"))["reward"])'     > /logs/verifier/reward.txt 2>/dev/null || echo 0 > /logs/verifier/reward.txt
}
trap fail_closed EXIT
# Root's PATH holds only root's directories: a build may write to /usr/local/cargo/bin (world-writable in the
# cleanroom images), and this script runs python3 after it. The evaluator gives the build its toolchains itself.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if ! python3 /opt/grader/evaluator.py || [ ! -s /logs/verifier/reward.json ]; then
  # the evaluator did not finish: whatever reward.json holds is not its result, and every test counts as failed
  printf '{"reward": 0.0, "resolved": 0.0, "almost_resolved": 0.0, "disqualified": 0.0}' > /logs/verifier/reward.json
fi
# The evaluator's result is Reward Kit's input; Reward Kit writes the reward (the trap mirrors it into reward.txt).
mv /logs/verifier/reward.json /logs/verifier/test_summary.json
echo 0 > /logs/verifier/reward.txt
cd /opt/rewardkit/workspace
/opt/rewardkit/bin/rewardkit /tests --workspace /opt/rewardkit/workspace --output /logs/verifier/reward.json
