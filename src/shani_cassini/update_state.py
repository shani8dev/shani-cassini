"""The background entry point: a tiny GApplication that owns the tray and a
periodic `shani-deploy --status --json` poll.

Reads only. Privileged actions (apply, rollback, set-channel) are invoked via
`pkexec shani-deploy ...`, same as Cassini, and are not done from a timer.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

DEPLOY = "shani-deploy"
POLL_INTERVAL_MS = 600_000  # 10 minutes


def current_status(run=subprocess.run) -> dict:
    """`shani-deploy --status --json`, as a dict that is always safe to render."""
    try:
        out = run([DEPLOY, "--status", "--json"], capture_output=True,
                  text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "problem": str(exc)}
    if not (out.stdout or "").strip():
        # rc=0 with nothing on stdout is NOT a success: json.loads would turn "" into
        # an empty document and mark it ok because rc says 0. The deploy engine
        # prints its state unconditionally, so no bytes is an engine problem.
        return {"ok": False, "problem": "shani-deploy said nothing"}
    try:
        doc = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "problem": "shani-deploy did not return JSON"}
    doc["ok"] = out.returncode == 0 and isinstance(doc, dict)
    if not doc["ok"] and "problem" not in doc:
        doc["problem"] = (out.stderr or "").strip() or "shani-deploy failed"
    return doc


def updates_available(status: dict) -> bool:
    """The one interesting line for a tray icon.

    `shani-deploy --status --json` is deliberately read-only: it reports state
    (slots, channel, boot markers) and does not itself check the remote.
    `--check` is the verb that does. This helper only reads what the status
    document carries, and never invents a "version available" that the deploy
    engine did not itself print.
    """
    if not status.get("ok"):
        return False
    markers = status.get("boot_markers") or {}
    return bool(markers.get("reboot_needed")) or bool(
        status.get("update_available"))


def summarize(status: dict) -> str:
    if not status.get("ok"):
        return f"Status unavailable: {status.get('problem', 'unknown')}"
    if updates_available(status):
        return "Update ready to apply — restart into it"
    slot = status.get("current_slot") or "unknown"
    return f"Up to date · slot {slot}"
