"""shani-cassini --agent: the background check at login and every 2 hours
(shani-cassini-agent.timer). It replaced shani-update (2026-09-25).

Reads `shani-deploy --status --check --json` and tells the user, once per
event, through desktop notifications (freedesktop notify-send with actions -
GNOME, Plasma and COSMIC all show them):

* the last boot of the updated system failed (the system already switched
  back by itself: shani-auto-rollback.timer) - or recovery itself failed;
* an update was installed and a restart finishes it;
* an update is available.

Clicking a notification opens Cassini on the matching page. Recovery and
installing stay with the system tools; the agent decides nothing itself.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REMIND_UPDATE_AFTER = 24 * 3600   # an ignored update is mentioned again a day later


def _state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "shani-cassini" / "agent.json"


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _load() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(p)


def _status() -> dict | None:
    try:
        r = subprocess.run(["shani-deploy", "--status", "--check", "--json"],
                           capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        logger.warning("shani-deploy --status failed: %s", e)
        return None


def pretty(v: str) -> str:
    return f"{v[:4]}.{v[4:6]}.{v[6:8]}" if len(v) == 8 and v.isdigit() else v


def decide(st: dict, state: dict, boot_id: str, now: float) -> list[dict]:
    """The notifications due, given the status and what was already said.
    Pure: no I/O - the tests drive it directly. Updates `state` in place."""
    out = []
    said = state.setdefault("said", {})
    failed = st.get("boot_hard_failure") or st.get("boot_failure") or ""
    if failed:
        key = f"failure:{boot_id}:{failed}"
        if key not in said:
            said[key] = now
            if st.get("auto_rollback_done") and st.get("booted_slot") == failed:
                out.append({"key": key, "urgency": "critical", "icon": "dialog-error",
                            "title": "Shanios could not recover automatically",
                            "body": f"The updated system (@{failed}) did not start and switching back failed. "
                                    "Open Shani Cassini to roll back.",
                            "section": "updates"})
            else:
                out.append({"key": key, "urgency": "critical", "icon": "dialog-warning",
                            "title": "The update did not start",
                            "body": f"The updated system (@{failed}) failed to boot, so Shanios started the "
                                    "previous one. Your files are safe.",
                            "section": "updates"})
    # candidate_boot only means the deployment is waiting for a reboot. The
    # reboot_needed event below is the truthful user-facing state; there is
    # no persistent first-boot marker and no first-start claim.
    reboot = st.get("reboot_needed") or ""
    if reboot:
        key = f"reboot:{boot_id}:{reboot}"
        if key not in said:
            said[key] = now
            out.append({"key": key, "urgency": "normal", "icon": "system-reboot",
                        "title": "Restart to finish the update",
                        "body": f"Shanios {pretty(reboot)} is installed and starts after a restart.",
                        "action": ("restart", "Restart Now"), "section": "updates"})
    elif st.get("update_available") is True:
        remote = (st.get("remote") or {}).get(st.get("channel") or "stable", "")
        key = f"update:{remote}"
        if key not in said or now - said[key] >= REMIND_UPDATE_AFTER:
            said[key] = now
            out.append({"key": key, "urgency": "normal", "icon": "software-update-available",
                        "title": f"Shanios {pretty(remote)} is available",
                        "body": "Install it from Shani Cassini - it goes into the other system slot, "
                                "your running system is not touched.",
                        "section": "updates"})
    # forget events of old boots so the file stays small
    for k in [k for k in said if k.count(":") >= 1 and not k.startswith("update:") and boot_id not in k]:
        del said[k]
    return out


def notify(n: dict) -> bool:
    """Deliver one notification; return True only when notify-send accepted it."""
    if not shutil.which("notify-send"):
        logger.warning("notify-send missing: %s", n["title"])
        return False
    argv = ["notify-send", "-a", "Shani Cassini", "-i", n["icon"], "-u", n["urgency"],
            "--action=open=Open"]
    if "action" in n:
        argv.append(f"--action={n['action'][0]}={n['action'][1]}")
    argv += ["--wait", n["title"], n["body"]]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=6 * 3600)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("notify-send failed for %s: %s", n["title"], e)
        return False
    if result.returncode != 0:
        logger.warning("notify-send rc=%s for %s", result.returncode, n["title"])
        return False
    choice = result.stdout.strip()
    if choice == "open":
        try:
            subprocess.Popen(["shani-cassini", f"--section={n['section']}"], start_new_session=True)
        except OSError as e:
            logger.warning("could not open Cassini: %s", e)
    elif choice == "restart":
        try:
            subprocess.run(["systemctl", "reboot"], check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            logger.warning("could not restart: %s", e)
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    st = _status()
    if st is None:
        return 0
    state = _load()
    todo = decide(st, state, _boot_id(), time.time())
    failed_delivery = False
    for n in todo:
        logger.info("notify: %s", n["title"])
        if notify(n):
            _save(state)
        else:
            failed_delivery = True
            state.get("said", {}).pop(n.get("key", ""), None)
    if failed_delivery and todo:
        # Remove unconfirmed keys from the file only when another event was saved.
        if any(n.get("key", "") in state.get("said", {}) for n in todo):
            _save(state)
    return 0
