"""The background agent's decisions (it replaced shani-update)."""

import json

import pytest

from shani_cassini.agent import decide, REMIND_UPDATE_AFTER

BASE = {"version": "20260925", "channel": "stable", "booted_slot": "blue", "current_slot": "blue",
        "previous_slot": "green", "boot_failure": "", "boot_hard_failure": "",
        "auto_rollback_done": False, "candidate_boot": False, "reboot_needed": "",
        "remote": {"stable": "20260925", "latest": "20260925"}, "update_available": False}


def st(**kw):
    return {**BASE, **kw}


def titles(ns):
    return [n["title"] for n in ns]


def test_quiet_when_nothing_happened():
    assert decide(st(), {}, "b1", 0) == []


def test_failed_boot_told_once_per_boot():
    state = {}
    s = st(boot_failure="green", booted_slot="blue")
    assert titles(decide(s, state, "b1", 0)) == ["The update did not start"]
    assert decide(s, state, "b1", 10) == []           # same boot: once
    assert titles(decide(s, state, "b2", 20)) == ["The update did not start"]  # next boot: again


def test_recovery_failure_is_its_own_message():
    s = st(boot_hard_failure="green", booted_slot="green", auto_rollback_done=True)
    n = decide(s, {}, "b1", 0)
    assert titles(n) == ["Shanios could not recover automatically"] and n[0]["urgency"] == "critical"


def test_candidate_boot_is_restart_required_not_first_start():
    s = st(candidate_boot=True, booted_slot="green", current_slot="blue", version="20261002")
    assert decide(s, {}, "b1", 0) == []

    s["reboot_needed"] = "20261002"
    assert titles(decide(s, {}, "b1", 0)) == ["Restart to finish the update"]


def test_failed_notification_is_retried_next_run(monkeypatch, tmp_path):
    from shani_cassini import agent

    calls = []
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(agent, "_status", lambda: st(reboot_needed="20261002"))
    monkeypatch.setattr(agent, "_boot_id", lambda: "b1")
    monkeypatch.setattr(agent, "_save", lambda state: pytest.fail("state saved before delivery"))
    monkeypatch.setattr(agent, "notify", lambda n: calls.append(n["title"]) or False)

    assert agent.main() == 0
    assert agent.main() == 0
    assert calls == ["Restart to finish the update", "Restart to finish the update"]


def test_successful_notification_is_persisted_once(monkeypatch, tmp_path):
    from shani_cassini import agent

    calls = []
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(agent, "_status", lambda: st(reboot_needed="20261002"))
    monkeypatch.setattr(agent, "_boot_id", lambda: "b1")
    monkeypatch.setattr(agent, "notify", lambda n: calls.append(n["title"]) or True)

    assert agent.main() == 0
    assert agent.main() == 0
    assert calls == ["Restart to finish the update"]
    state = json.loads(agent._state_path().read_text())
    assert "reboot:b1:20261002" in state["said"]


def test_restart_needed_wins_over_update_and_offers_restart():
    s = st(reboot_needed="20261002", update_available=True, remote={"stable": "20261002"})
    n = decide(s, {}, "b1", 0)
    assert titles(n) == ["Restart to finish the update"] and n[0]["action"][0] == "restart"


def test_update_reminded_after_a_day_not_every_two_hours():
    state = {}
    s = st(update_available=True, remote={"stable": "20261002", "latest": "20261002"})
    assert titles(decide(s, state, "b1", 0)) == ["Shanios 2026.10.02 is available"]
    assert decide(s, state, "b1", 2 * 3600) == []
    assert titles(decide(s, state, "b2", REMIND_UPDATE_AFTER + 1)) == ["Shanios 2026.10.02 is available"]


def test_old_boot_events_are_forgotten():
    state = {}
    decide(st(candidate_boot=True, booted_slot="green"), state, "b1", 0)
    decide(st(), state, "b2", 1)
    assert not any("b1" in k for k in state["said"])
