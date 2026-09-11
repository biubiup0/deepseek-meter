#!/usr/bin/env python3
"""Codex ``Stop`` hook: show DeepSeek balance and this session's spend.

``Stop`` requires JSON on stdout, so the summary is returned through
``systemMessage``, which Codex surfaces in the UI. The hook never continues the
turn (no ``decision: block``) and always exits 0 with valid JSON.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deepseek_meter as meter  # noqa: E402


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def summarize_with_retry(transcript, turn_id, attempts: int = 4, delay: float = 0.8):
    """The turn's usage record can land just after the hook fires."""
    summary = meter.summarize_transcript(transcript, scope="turn", turn_id=turn_id)
    tries = 0
    while not summary.get("calls") and tries < attempts:
        time.sleep(delay)
        summary = meter.summarize_transcript(transcript, scope="turn", turn_id=turn_id)
        tries += 1
    return summary


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    if not isinstance(event, dict):
        event = {}

    # Codex already continued this turn from a Stop hook: stay quiet.
    if event.get("stop_hook_active"):
        emit({"continue": True})
        return 0

    try:
        # Once a day this pulls the official price table; otherwise it is a no-op.
        meter.refresh_prices_if_stale()

        transcript = event.get("transcript_path")
        if not transcript:
            found = meter.find_transcript(event.get("session_id") or "")
            transcript = str(found) if found else None

        summary = summarize_with_retry(transcript, event.get("turn_id")) if transcript else None
        summary = summary or meter.summarize_transcript(None, scope="turn")
        meter.log(
            "stop hook: session=%s turn=%s transcript=%s exists=%s calls=%d"
            % (
                event.get("session_id"),
                event.get("turn_id"),
                transcript,
                bool(transcript) and os.path.exists(transcript),
                int(summary.get("calls") or 0),
            )
        )
        if not summary.get("calls"):
            emit({"continue": True})
            return 0

        ttl = int(os.environ.get("DEEPSEEK_METER_CACHE_TTL") or meter.DEFAULT_CACHE_TTL)
        balance = meter.fetch_balance(ttl=ttl, timeout=6.0)
        message = meter.one_line(summary, balance)
        emit({"continue": True, "systemMessage": message})
    except Exception as exc:  # never break the session because of this hook
        meter.log("stop hook failed: %r" % (exc,))
        emit({"continue": True})
    return 0


if __name__ == "__main__":
    sys.exit(main())
