"""Run harbor-rewardkit 0.2.4 (unmodified) for godzilla's judge stage, then log the judge's model calls.

rewardkit's Codex judge runs `codex exec` sessions and saves each one in /logs/judge (trajectory.codex.*.jsonl; a session
whose process failed leaves process.codex.*.txt). When rewardkit has ended, every model response those sessions
recorded is written to judge_calls.jsonl, one JSON object per line: the session, the model asked for and the one that
answered, the tokens, and on a session's last response how it ended and which criteria it answered. The log only
reports; it never changes a verdict.
"""
import glob
import json
import os
import re
import sys

LOG_DIR = '/logs/judge'
LOG = os.path.join(LOG_DIR, 'judge_calls.jsonl')
REQUESTED = 'openai/gpt-6.1-sol'
ENDINGS = ("task_complete", "turn_aborted", "error", "stream_error")


def answered(message):
    """The criteria a session's final message gives verdicts for (its JSON object's keys)."""
    if not isinstance(message, str):
        return []
    match = re.search(r"\{.*\}", message, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        return []
    return sorted(data) if isinstance(data, dict) else []


def calls(path):
    name, records, served, session = os.path.basename(path), [], None, None
    with open(path, errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind, payload = event.get("type"), event.get("payload") or {}
            if kind == "session_meta":
                session = payload.get("session_id") or payload.get("id")
            elif kind == "turn_context":
                served = payload.get("model") or served
            elif kind == "token_usage_record":
                usage = payload.get("usage") or {}
                records.append({"time": event.get("timestamp"), "session": name, "session_id": session,
                                "response_id": payload.get("response_id"), "requested": REQUESTED, "served_by": served,
                                "stop_reason": None, "criteria": [], "input_tokens": usage.get("input_tokens"),
                                "cache_read_input_tokens": usage.get("cached_input_tokens"),
                                "output_tokens": usage.get("output_tokens"),
                                "reasoning_output_tokens": usage.get("reasoning_output_tokens")})
            elif kind == "event_msg" and payload.get("type") in ENDINGS:
                end = {"stop_reason": payload.get("type"), "criteria": answered(payload.get("last_agent_message"))}
                if records and records[-1]["stop_reason"] is None:
                    records[-1].update(end)
                else:
                    records.append({"time": event.get("timestamp"), "session": name, "session_id": session,
                                    "requested": REQUESTED, "served_by": served, **end})
    return records


def write_log():
    with open(LOG, "w") as out:
        for path in sorted(glob.glob(os.path.join(LOG_DIR, "trajectory.codex.*.jsonl"))):
            for record in calls(path):
                out.write(json.dumps(record) + "\n")
        for path in sorted(glob.glob(os.path.join(LOG_DIR, "process.codex.*"))):
            out.write(json.dumps({"session": os.path.basename(path), "requested": REQUESTED,
                                  "stop_reason": "process_failed"}) + "\n")


from rewardkit.__main__ import main  # noqa: E402

sys.argv[0] = "rewardkit"
code = 1
try:
    code = main()
except SystemExit as stop:
    code = stop.code
finally:
    try:
        write_log()
    except Exception as exc:  # the log never changes a verdict
        print(f"judge call log failed: {exc!r}", file=sys.stderr)
sys.exit(code)
