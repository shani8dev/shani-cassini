"""The pages against the real CLI contracts, with fake shani-deploy /
shani-health / pkexec on PATH printing what the real ones print."""

import json
import os
import stat
import time

import pytest
from gi.repository import GLib

STATUS = {"version": "20260921", "profile": "gnome", "channel": "stable", "booted_slot": "blue",
          "current_slot": "blue", "previous_slot": "green", "boot_failure": "",
          "boot_hard_failure": False, "auto_rollback_done": False, "candidate_boot": True,
          "reboot_needed": True,
          "remote": {"stable": "20260925", "latest": "20260925"}, "update_available": True}
VERIFY = {"ok": False, "errors": 1, "checks": [
    {"name": "uki-blue", "status": "pass", "message": "signature valid"},
    {"name": "esp-space", "status": "fail", "message": "ESP 97% full"},
    {"name": "swap", "status": "warn", "message": "no swapfile"}]}


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    def write(name, body):
        f = tmp_path / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    write("shani-deploy", f"echo '{json.dumps(STATUS)}'\n")
    # shani-health --verify exits 1 when a check fails, still printing JSON
    write("shani-health", "case \"$1\" in --verify) echo '%s'; exit 1 ;; *) echo '%s' ;; esac\n" % (json.dumps(VERIFY), json.dumps({"checks": []})))
    write("pkexec", 'exec "$@"\n')
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


def spin(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def test_overview_shows_status(fake_bin):
    from shani_cassini.tabs.overview import OverviewTab
    tab = OverviewTab()
    assert spin(lambda: tab._title.get_label() == "Shanios 2026.09.21")
    assert tab._subtitle.get_label() == "Gnome edition"
    assert tab._pill.get_label() == "Update available: 2026.09.25"
    assert "@blue" in tab._rows["slot"].get_subtitle() and "@green" in tab._rows["slot"].get_subtitle()


def test_updates_page_offers_update_and_rollback(fake_bin):
    from shani_cassini.tabs.updates import UpdatesTab
    tab = UpdatesTab()
    assert spin(lambda: tab._btn_update.get_visible())
    assert tab._row_update.get_title() == "Shanios 2026.09.25 is available"
    assert tab._btn_rollback.get_sensitive()
    assert tab._channel.get_selected() == 0  # stable


def test_updates_page_without_deploy(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # no shani-deploy at all
    from shani_cassini.tabs.updates import UpdatesTab
    tab = UpdatesTab()
    assert spin(lambda: tab._row_update.get_title() == "Cannot read the system state")
    assert not tab._btn_rollback.get_sensitive()


def test_health_shows_failures_first_despite_exit_1(fake_bin):
    from shani_cassini.tabs.health import HealthTab
    tab = HealthTab()
    tab._run("verify")
    assert spin(lambda: getattr(tab, "_group_verify", None) is not None)
    g = tab._group_verify
    assert g.get_description().startswith("1 problem, 1 warning")


@pytest.fixture
def health_pkexec_log(fake_bin):
    log = fake_bin / "health-pkexec.log"
    (fake_bin / "pkexec").write_text(
        f'#!/bin/sh\necho "$@" >> {log}\nexec "$@"\n')
    (fake_bin / "pkexec").chmod(0o755)
    return log


def test_health_exposes_supported_report_modes(health_pkexec_log):
    from shani_cassini.tabs.health import HealthTab
    tab = HealthTab()
    modes = {"security", "boot", "hardware", "network", "packages", "storage-info"}
    assert set(tab._run_rows) == {"verify", *modes}
    for mode in sorted(modes):
        tab._run(mode)
        assert spin(lambda mode=mode: getattr(tab, f"_group_{mode}", None) is not None)
    assert set(health_pkexec_log.read_text().splitlines()) == {
        f"shani-health --{mode} --json" for mode in modes
    }


def test_system_boot_card_uses_only_real_deploy_fields(fake_bin, monkeypatch):
    from shani_cassini.tabs.system import SystemTab
    from shani_cassini.widgets import find_named

    for method in ("_fetch_hardware_info", "_fetch_storage_info"):
        monkeypatch.setattr(SystemTab, method, lambda self: None)
    tab = SystemTab()
    assert spin(lambda: find_named(tab, "boot-current") is not None
               and find_named(tab, "boot-current").get_label() == "@blue")
    assert find_named(tab, "boot-current").get_label() == "@blue"
    assert find_named(tab, "boot-marker").get_label() == "@blue"
    assert find_named(tab, "boot-deployment").get_label() == "Awaiting reboot"
    assert find_named(tab, "boot-reboot").get_label() == "Required"
    assert find_named(tab, "boot-failure").get_label() == "None reported"
    assert find_named(tab, "boot-recovery").get_label() == "Not attempted"
    for name in ("boot-expected", "boot-candidate", "boot-uki", "boot-entries"):
        assert find_named(tab, name) is None
    assert find_named(tab, "services-flow-box") is None


@pytest.fixture
def pkexec_log(fake_bin):
    log = fake_bin / "pkexec.log"
    (fake_bin / "pkexec").write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    return log


def test_loading_the_channel_does_not_change_it(pkexec_log):
    """Showing the current channel must not fire --set-channel (the old
    page's programmatic-init guard)."""
    from shani_cassini.tabs.updates import UpdatesTab
    tab = UpdatesTab()
    assert spin(lambda: tab._btn_update.get_visible())
    spin(lambda: False, timeout=0.5)
    assert not pkexec_log.exists()


def test_changing_the_channel_runs_set_channel(pkexec_log):
    from shani_cassini.tabs.updates import UpdatesTab
    tab = UpdatesTab()
    assert spin(lambda: tab._btn_update.get_visible())
    tab._channel.set_selected(1)  # Latest
    assert spin(lambda: pkexec_log.exists())
    assert pkexec_log.read_text().strip() == "shani-deploy --set-channel latest"


@pytest.fixture
def fake_genefi(fake_bin):
    status = {"encrypted": True, "tpm2_present": True, "tpm2_enrolled": True, "tpm2_slots": 1,
              "tpm2_pin": False, "secure_boot": True, "luks_device": "/dev/nvme0n1p2"}
    (fake_bin / "gen-efi").write_text(
        "#!/bin/sh\n"
        f'echo "$@" > {fake_bin}/genefi.args\n'
        # like the real one: only enroll/remove read stdin
        f'[ "$1" = tpm2-status ] || cat > {fake_bin}/genefi.stdin\n'
        f'[ "$1" = tpm2-status ] && echo \'{json.dumps(status)}\'\n'
        "exit 0\n")
    (fake_bin / "gen-efi").chmod(0o755)
    return fake_bin


def test_encryption_status(fake_genefi, monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "has_tpm2", lambda: True)
    tab = encryption.EncryptionTab()
    tab._load_status()
    assert spin(lambda: tab._btn_remove.get_sensitive())
    assert tab._status_row.get_subtitle().startswith("On - unlocks with the TPM; bound to the firmware and Secure Boot")


def test_enroll_passes_secrets_on_stdin_only(fake_genefi, monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "has_tpm2", lambda: True)
    tab = encryption.EncryptionTab()
    tab._run_with_stdin(["pkexec", "gen-efi", "enroll-tpm2", "--stdin", "--with-pin"],
                        "my secret phrase\n1234\n", "ok", "fail")
    assert spin(lambda: (fake_genefi / "genefi.stdin").exists() and (fake_genefi / "genefi.args").exists())
    args = (fake_genefi / "genefi.args").read_text()
    assert args.strip() == "enroll-tpm2 --stdin --with-pin"
    assert "secret" not in args and "1234" not in args
    assert (fake_genefi / "genefi.stdin").read_text() == "my secret phrase\n1234\n"


def test_unencrypted_disk_offers_no_tpm_actions(monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: False)
    tab = encryption.EncryptionTab()
    assert not hasattr(tab, "_btn_enroll")


def test_services_lists_only_toggleable_and_toggles(tmp_path, monkeypatch):
    files = [{"unit_file": "sshd.service", "state": "disabled", "preset": "disabled"},
             {"unit_file": "cups.service", "state": "enabled", "preset": "enabled"},
             {"unit_file": "systemd-journald.service", "state": "static", "preset": None},
             {"unit_file": "getty@.service", "state": "enabled", "preset": "enabled"}]
    units = [{"unit": "cups.service", "load": "loaded", "active": "active", "sub": "running",
              "description": "CUPS Scheduler"}]
    log = tmp_path / "systemctl.log"
    f = tmp_path / "systemctl"
    f.write_text("#!/bin/sh\n"
                 f'case "$1" in list-unit-files) echo \'{json.dumps(files)}\' ;; '
                 f'list-units) echo \'{json.dumps(units)}\' ;; *) echo "$@" >> {log} ;; esac\n')
    f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    from shani_cassini.tabs.services import ServicesTab
    tab = ServicesTab()
    assert spin(lambda: len(tab._rows) == 2)  # no static unit, no template
    assert tab._running.get_title() == "Running (1)" and tab._stopped.get_title() == "Not Running (1)"
    sshd_row = next(r for r, h in tab._rows if h.startswith("sshd"))
    sw = next(w for w in _descendants(sshd_row) if isinstance(w, __import__("gi").repository.Gtk.Switch))
    sw.set_active(True)
    assert spin(lambda: log.exists())
    assert log.read_text().strip() == "enable --now sshd.service"


def _descendants(w):
    c = w.get_first_child()
    while c is not None:
        yield c
        yield from _descendants(c)
        c = c.get_next_sibling()


def test_old_shani_deploy_gets_a_plain_message(tmp_path, monkeypatch):
    f = tmp_path / "shani-deploy"
    f.write_text("#!/bin/sh\nprintf '\\033[1;31m2026-09-25 10:19:26 [FATAL] Invalid option: --status\\033[0m\\n' >&2\nexit 1\n")
    f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    from shani_cassini.tabs.overview import OverviewTab
    tab = OverviewTab()
    assert spin(lambda: tab._subtitle.get_label() != "Reading system state…")
    assert tab._subtitle.get_label() == "This system's tools are older than Shani Cassini - update Shanios to see this"
    assert "\x1b" not in tab._subtitle.get_label()


CHRONOA_SCHEMA = """<schemalist><schema id="org.shani.chronoa" path="/org/shani/chronoa/">
<key name="privacy-mode" type="b"><default>true</default></key>
<key name="auto-start" type="b"><default>false</default></key>
<key name="wake-word-enabled" type="b"><default>false</default></key>
<key name="model" type="s"><default>''</default></key>
<key name="ollama-host" type="s"><default>'http://127.0.0.1:9'</default></key>
<key name="openai-api-key" type="s"><default>'sk-secret'</default></key>
</schema></schemalist>"""


def test_chronoa_page_binds_its_settings(tmp_path):
    import subprocess
    (tmp_path / "org.shani.chronoa.gschema.xml").write_text(CHRONOA_SCHEMA)
    subprocess.run(["glib-compile-schemas", str(tmp_path)], check=True)
    code = f"""
import os, sys
os.environ["GSETTINGS_SCHEMA_DIR"] = {str(tmp_path)!r}; os.environ["GSETTINGS_BACKEND"] = "memory"
sys.path.insert(0, "src")
from gi.repository import Adw, Gio
from shani_cassini.tabs.chronoa import ChronoaTab
t = ChronoaTab()
def walk(w):
    c = w.get_first_child()
    while c is not None:
        yield c; yield from walk(c); c = c.get_next_sibling()
rows = {{r.get_title(): r for r in walk(t) if isinstance(r, Adw.SwitchRow)}}
assert set(rows) == {{"Privacy mode", "Start at login", "Wake word"}}, rows
assert rows["Privacy mode"].get_active() is True
rows["Start at login"].set_active(True)
assert Gio.Settings.new("org.shani.chronoa").get_boolean("auto-start") is True
texts = [getattr(w, "get_text", lambda: "")() for w in walk(t)] + [getattr(w, "get_subtitle", lambda: "")() for w in walk(t)]
assert not any("sk-secret" in (x or "") for x in texts), "an API key is displayed"
print("ok")
"""
    r = subprocess.run([__import__("sys").executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr
