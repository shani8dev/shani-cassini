"""The pages against the real CLI contracts, with fake shani-deploy /
shani-health / pkexec on PATH printing what the real ones print."""

import json
import os
import shutil
import stat
import time
from pathlib import Path

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


def _fake_sys(tmp_path, monkeypatch, *, cpuinfo=None, meminfo=None, thermal=None,
              battery=None, lspci="", bluetooth=""):
    """Point the hardware collectors at files a test controls.

    The paths are module constants for exactly this reason: before the
    extraction the page hardcoded /proc and /sys inline, so none of this
    parsing could be exercised without a real machine.
    """
    from shani_cassini import system_status as ss
    root = tmp_path / "sys"
    root.mkdir(exist_ok=True)
    wanted = {
        "PROC_CPUINFO": cpuinfo,
        "PROC_MEMINFO": meminfo,
        "THERMAL_ZONE": thermal,
    }
    for const, body in wanted.items():
        path = root / const
        if body is not None:
            path.write_text(body)
        monkeypatch.setattr(ss, const, str(path))
    base = root / "BAT0"
    if battery is not None:
        base.mkdir()
        (base / "capacity").write_text(battery["capacity"])
        (base / "status").write_text(battery["status"])
    # Always repointed, even when there is no battery to write: this host has a
    # real one, and a fake that falls through to /sys answers with this
    # machine's 98% rather than the fixture's, which is worse than no fake.
    monkeypatch.setattr(ss, "POWER_SUPPLY", str(base))
    # Repointed for the same reason as the battery above: this host has 7 real
    # hwmon chips, so a fall-through answers with this machine's temperatures.
    monkeypatch.setattr(ss, "HWMON_ROOT", str(root / "hwmon"))
    for name, body in (("lspci", lspci), ("bluetoothctl", bluetooth)):
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\ncat <<'EOF'\n" + body + "\nEOF\n")
        tool.chmod(0o755)
    ppd = tmp_path / "powerprofilesctl"
    ppd.write_text("#!/bin/sh\ncase \"$1\" in\n"
                   f'  get) printf "%b" {PPD_GET!r} ;;\n'
                   f'  list) printf "%b" {PPD_LIST!r} ;;\nesac\n')
    ppd.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def test_the_hardware_card_is_drivable_from_fakes(tmp_path, monkeypatch):
    """Each reading is answered by the fixture, not by this machine."""
    from shani_cassini import system_status as ss
    _fake_sys(
        tmp_path, monkeypatch,
        cpuinfo="processor\t: 0\nmodel name\t: Fake CPU 9000\nprocessor\t: 1\n"
                "processor\t: 2\nflags\t: fpu vme svm\n",
        meminfo="MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\n",
        thermal="45000\n",
        battery={"capacity": "77\n", "status": "Discharging\n"},
        lspci="00:02.0 VGA compatible controller: Fake GPU 7",
        bluetooth="Powered: yes\n",
    )
    out = {}
    ss.hardware_card(lambda r: out.update(r))
    assert spin(lambda: len(out) == 8), out
    assert out["hw-cpu"] == "Fake CPU 9000 (3 threads)"
    assert out["hw-cpu-temp"] == "45°C"
    assert out["hw-gpu"] == "Fake GPU 7"
    assert out["hw-ram"] == "16000 MB (8000 MB used)"
    assert out["hw-battery"] == "77% (Discharging)"
    assert out["hw-virt"] == "VT-x/AMD-V available"
    assert out["hw-bluetooth"] == "● Active"


def test_a_hardware_source_that_is_absent_falls_back_on_its_own_row_only(
        tmp_path, monkeypatch):
    """The battery is missing; the other six readings are still taken.

    This is the behaviour that used to be impossible to state, because the
    page owned the parsing and had no seam to fake a /sys that is not there.
    """
    from shani_cassini import system_status as ss
    _fake_sys(
        tmp_path, monkeypatch,
        cpuinfo="model name\t: Fake CPU\nprocessor\t: 0\n",
        meminfo="MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n",
        thermal="40000\n",
        battery=None,
        lspci="",
        bluetooth="Powered: no\n",
    )
    out = {}
    ss.hardware_card(lambda r: out.update(r))
    assert spin(lambda: len(out) == 8), out
    assert out["hw-battery"] == "N/A"
    assert out["hw-cpu"] == "Fake CPU (1 threads)"
    assert out["hw-ram"] == "1024 MB (512 MB used)"
    assert out["hw-gpu"] == "Unknown"
    assert out["hw-bluetooth"] == "○ Inactive"


def test_one_unreadable_source_does_not_blank_the_whole_hardware_card(
        monkeypatch):
    """Each hardware reading is independent, so one that cannot be taken is
    reported on its own row and leaves the rest alone.

    They were one try block: a /proc/meminfo without a MemTotal line raised
    IndexError at the RAM row, and the handler around the whole card then
    skipped battery, virtualisation and bluetooth, which were left showing
    the "" they are created with. A missing thermal zone is normal on a
    desktop; it must not cost the reader the battery.
    """
    from shani_cassini.tabs.system import SystemTab
    from shani_cassini.widgets import find_named

    def no_meminfo(*_a, **_k):
        raise FileNotFoundError("/proc/meminfo")

    monkeypatch.setattr("builtins.open", no_meminfo)
    tab = SystemTab()
    tab._fetch_hardware_info()

    def label(name):
        w = find_named(tab, name)
        return w.get_label() if w is not None else None

    # the one that failed says so, rather than aborting the card
    assert spin(lambda: label("hw-ram") == "N/A"), label("hw-ram")
    # and the ones after it in the same try block were still taken
    assert label("hw-battery") not in (None, ""), "battery was skipped by the RAM failure"
    assert label("hw-virt") not in (None, ""), "virtualisation was skipped by the RAM failure"
    assert label("hw-bluetooth") not in (None, ""), "bluetooth was skipped by the RAM failure"


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
    assert spin(lambda: pkexec_log.exists() and pkexec_log.stat().st_size > 0)
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


def _tpm_present(value):
    """Stand in for ss.tpm2_present(), answering without spawning a tool."""
    return lambda done: done(value, "")


def test_encryption_status(fake_genefi, monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "tpm2_present", _tpm_present(True))
    tab = encryption.EncryptionTab()
    tab._load_status()
    assert spin(lambda: tab._btn_remove.get_sensitive())
    assert tab._status_row.get_subtitle().startswith("On - unlocks with the TPM; bound to the firmware and Secure Boot")


def test_enroll_passes_secrets_on_stdin_only(fake_genefi, monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "tpm2_present", _tpm_present(True))
    tab = encryption.EncryptionTab()
    tab._run_with_stdin(["pkexec", "gen-efi", "enroll-tpm2", "--stdin", "--with-pin"],
                        "my secret phrase\n1234\n", "ok", "fail")
    # Wait for the CONTENT, not the file: the fake runs `cat > genefi.stdin`, so
    # the shell creates that file empty and only fills it once stdin reaches EOF.
    # Waiting on exists() alone returned while the file was still empty, and this
    # failed roughly two runs in three with `assert '' == 'my secret phrase...'`.
    def _stdin_landed():
        f = fake_genefi / "genefi.stdin"
        return f.exists() and f.stat().st_size > 0

    assert spin(lambda: _stdin_landed() and (fake_genefi / "genefi.args").exists())
    args = (fake_genefi / "genefi.args").read_text()
    assert args.strip() == "enroll-tpm2 --stdin --with-pin"
    assert "secret" not in args and "1234" not in args
    assert (fake_genefi / "genefi.stdin").read_text() == "my secret phrase\n1234\n"


def test_unencrypted_disk_offers_no_tpm_actions(monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: False)
    tab = encryption.EncryptionTab()
    assert not hasattr(tab, "_btn_enroll")


def test_the_tpm_row_reads_checking_before_the_answer_arrives(monkeypatch):
    """The page must be on screen before the probe answers.

    Holding the callback open is the whole point: if _build() waited for the
    value, the subtitle would already be "Available" here and the row would
    never be seen mid-flight.
    """
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    pending = []
    monkeypatch.setattr(encryption.ss, "tpm2_present", lambda done: pending.append(done))
    tab = encryption.EncryptionTab()
    assert pending, "the page asked nobody about the TPM"
    assert tab._tpm_row.get_subtitle() == "Checking…"
    pending[0](True, "")
    assert tab._tpm_row.get_subtitle() == "Available"


def test_the_enroll_button_follows_the_tpm_answer(monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    for tpm, expected in ((True, True), (False, False), (None, False)):
        monkeypatch.setattr(encryption.ss, "tpm2_present", _tpm_present(tpm))
        tab = encryption.EncryptionTab()
        assert tab._btn_enroll.get_sensitive() is expected, f"tpm={tpm}"


def test_an_unanswerable_probe_says_unknown_and_does_not_blame_the_firmware(monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "tpm2_present", _tpm_present(None))
    tab = encryption.EncryptionTab()
    assert tab._tpm_row.get_subtitle() == "Unknown"


def test_a_tpm_read_from_a_previous_build_cannot_land_on_a_fresh_row(monkeypatch):
    """_build() runs again after every enrol and every remove.

    A read spawned by the previous build can therefore land after the row it
    was going to fill has been discarded. The answer has to go to the row the
    read was spawned for, not to whatever self._tpm_row happens to be by then.
    """
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    pending = []
    monkeypatch.setattr(encryption.ss, "tpm2_present", lambda done: pending.append(done))
    tab = encryption.EncryptionTab()
    stale = pending.pop()
    tab._build()
    assert tab._tpm_row.get_subtitle() is not None
    stale(False, "")
    assert "firmware" not in (tab._tpm_row.get_subtitle() or ""), (
        "a discarded read wrote to the current row")


def test_run_status_reports_the_exit_code_even_when_stdout_is_empty(fake_bin):
    """systemd-analyze has-tpm2 -q prints nothing; run_text calls that a failure.

    The one case that matters -- a working TPM -- prints the least, so a reader
    that needs output to call the read a success reports the good answer as the
    broken one.
    """
    from shani_cassini import system_status as ss
    fake = fake_bin / "systemd-analyze"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    out = []
    ss.run_status(["systemd-analyze", "has-tpm2", "-q"], lambda st, err: out.append((st, err)))
    assert spin(lambda: bool(out))
    assert out[0] == (0, ""), out[0]


def test_tpm2_present_reads_the_tpm_from_the_exit_code(fake_bin, monkeypatch):
    from shani_cassini import system_status as ss
    fake = fake_bin / "systemd-analyze"

    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    out = []
    ss.tpm2_present(lambda tpm, err: out.append((tpm, err)))
    assert spin(lambda: bool(out))
    assert out[0] == (True, ""), out[0]

    out.clear()
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    ss.tpm2_present(lambda tpm, err: out.append((tpm, err)))
    assert spin(lambda: bool(out))
    assert out[0] == (False, ""), out[0]

    out.clear()
    # Deleting the fake is not enough: the real systemd-analyze is on PATH on a
    # systemd host, so `which` would still find it and this would be testing
    # nothing. Empty PATH is what actually makes the tool absent.
    empty = fake_bin / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    ss.tpm2_present(lambda tpm, err: out.append((tpm, err)))
    assert spin(lambda: bool(out))
    assert out[0][0] is None, out[0]


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
    assert spin(lambda: log.exists() and log.stat().st_size > 0)
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
<!-- Added 2026-10-03. The Chronoa page binds six keys and this fixture declared
     three, so the test that exists precisely to catch "the page binds a key the
     compiled schema does not declare" was itself failing that check. Types and
     defaults are copied from the real shipped schema,
     shani-chronoa/pkg/shani-chronoa/usr/share/glib-2.0/schemas/
     org.shani.chronoa.gschema.xml - not invented. -->
<key name="notification-enabled" type="b"><default>true</default></key>
<key name="cloud-fallback-enabled" type="b"><default>false</default></key>
<key name="wake-phrase" type="s"><default>''</default></key>
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
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")   # without this, PyGIWarning is emitted first
from gi.repository import Adw, Gio
from shani_cassini.tabs.chronoa import ChronoaTab
t = ChronoaTab()
def walk(w):
    c = w.get_first_child()
    while c is not None:
        yield c; yield from walk(c); c = c.get_next_sibling()
rows = {{r.get_title(): r for r in walk(t) if isinstance(r, Adw.SwitchRow)}}
# The page's five switches, asserted by title. This list was three entries and
# the page has bound five since the wake-phrase and cloud-fallback work, so the
# test was asserting against a page that no longer exists - and, like the schema
# fixture above, it is the "does the page bind what it claims" check that was
# itself out of date. Read off the widget tree, not off the source.
assert set(rows) == {{"Privacy mode", "Start at login", "Wake phrase",
                     "Spoken replies", "Cloud fallback"}}, rows
assert rows["Privacy mode"].get_active() is True
rows["Start at login"].set_active(True)
assert Gio.Settings.new("org.shani.chronoa").get_boolean("auto-start") is True
texts = [getattr(w, "get_text", lambda: "")() for w in walk(t)] + [getattr(w, "get_subtitle", lambda: "")() for w in walk(t)]
assert not any("sk-secret" in (x or "") for x in texts), "an API key is displayed"
print("ok")
"""
    r = subprocess.run([__import__("sys").executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
    assert r.returncode == 0 and "ok" in r.stdout, r.stdout + r.stderr


# --- the Device card: clock and boot time, off the main thread ---------------
# These two used to be read with subprocess.run inside DeviceGroup.__init__,
# which is the GTK main thread while the page is being built. That put a
# 10s-timeout call there, twice, and the comment claimed they were "small,
# local, fast" -- true for a healthy boot and not true for a stalled
# systemd-timedated or a large boot journal. hostnamectl() on the adjacent line
# was already asynchronous, so the module was mixing both patterns.
#
# The regression this guards is the *shape* of the fix, not the strings: a
# synchronous subprocess.run in a widget's __init__ is the defect, so these
# assert the page renders real values, and the AST gate below is what stops the
# synchronous read coming back.

TIMEDATECTL_SHOW = """         LocalRTC=no
             Timezone=Europe/London
     NTPSynchronized=yes
"""

SYSTEMD_ANALYZE_TIME = """Startup finished in 4.281s (firmware) + 12.5M (loader) + 1.204s (kernel) + 2.113s (initrd) = 4.5s
"""


def _device_fakes(tmp_path, *, timedate=TIMEDATECTL_SHOW, analyze=SYSTEMD_ANALYZE_TIME,
                  analyze_rc=0):
    def write(name, body):
        f = tmp_path / name
        f.write_text("#!/bin/sh\ncat <<'EOF'\n" + body + "\nEOF\n")
        f.chmod(0o755)
    write("hostnamectl", '{"HardwareVendor":"","HardwareModel":"","Chassis":"",'
                         '"FirmwareVendor":"","FirmwareVersion":"","FirmwareDate":"0",'
                         '"OperatingSystemPrettyName":"Shanios","KernelRelease":"7.2.6"}\n')
    if timedate is not None:
        write("timedatectl", timedate)
    if analyze is not None:
        write("systemd-analyze", f"{analyze}\nexit {analyze_rc}\n")
    return tmp_path


def test_device_card_renders_clock_and_boot_time(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_device_fakes(tmp_path)}:{os.environ['PATH']}")
    from shani_cassini.tabs.device import DeviceGroup
    g = DeviceGroup()
    assert spin(lambda: g._rows["clock"].get_subtitle() != "…")
    assert spin(lambda: g._rows["boot"].get_subtitle() != "…")
    assert g._rows["clock"].get_subtitle() == "Europe/London · synchronized with network time"
    assert g._rows["boot"].get_subtitle() == "4.5s"


def test_device_card_says_unsynced_rather_than_nothing(tmp_path, monkeypatch):
    unsynced = TIMEDATECTL_SHOW.replace("NTPSynchronized=yes", "NTPSynchronized=no")
    monkeypatch.setenv("PATH", f"{_device_fakes(tmp_path, timedate=unsynced)}:{os.environ['PATH']}")
    from shani_cassini.tabs.device import DeviceGroup
    g = DeviceGroup()
    assert spin(lambda: "·" in g._rows["clock"].get_subtitle())
    assert g._rows["clock"].get_subtitle() == "Europe/London · not synchronized"


def test_device_card_boot_time_survives_a_non_zero_exit(tmp_path, monkeypatch):
    """systemd-analyze time can exit non-zero and still print the figure. A
    caller that treated the status as the answer would report Unknown for a
    number the tool had already given us."""
    monkeypatch.setenv("PATH", f"{_device_fakes(tmp_path, analyze_rc=1)}:{os.environ['PATH']}")
    from shani_cassini.tabs.device import DeviceGroup
    g = DeviceGroup()
    assert spin(lambda: g._rows["boot"].get_subtitle() != "…")
    assert g._rows["boot"].get_subtitle() == "4.5s"


def test_device_card_says_unknown_when_the_tool_is_absent(tmp_path, monkeypatch):
    # PATH is tmp_path ALONE, not prepended: prepending would still find the
    # host's real timedatectl and prove nothing about the absent case.
    _device_fakes(tmp_path, timedate=None, analyze=None)
    monkeypatch.setenv("PATH", str(tmp_path))
    from shani_cassini.tabs.device import DeviceGroup
    g = DeviceGroup()
    assert spin(lambda: g._rows["clock"].get_subtitle() == "Unknown")
    assert g._rows["boot"].get_subtitle() == "Unknown"


def test_device_card_never_shells_out_synchronously():
    """The defect, pinned structurally. A grep for subprocess would miss a
    regression reintroduced as any other blocking reader, so this reads the AST
    and fails on a synchronous subprocess use anywhere in the module."""
    import ast
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[1] / "src/shani_cassini/tabs/device.py").read_text()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen", "check_output", "call", "check_call")
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    assert not calls, f"device.py blocks the GTK main thread again: {calls}"
    assert "subprocess" not in src, "device.py imports subprocess again"


# --- the System Info cards: hardware and storage -------------------------
# The Device card above was fixed for running its reads off the main thread.
# These two cards were not, and they sit on the same page: SystemTab.__init__
# calls _update_data, which calls both, and _update_data runs while
# notebook.py builds the page -- so every one of these reads was a synchronous
# subprocess.run on the GTK main thread. Measured on the running code with
# fakes that sleep: constructing SystemTab() took 6.33s for 6.00s of tool
# time, i.e. the window was frozen for the whole sum. Worst single read is
# `du -sh /var/log`, capped at 30s, which is why "small, local, fast" is a
# comment and not a guarantee.
#
# The parsers are split out as pure functions for the same reason the page's
# parsing was moved here at all: the shape of the output is testable with no
# subprocess, no /proc and no main loop, and the only thing left to get right
# at runtime is that the reads are not on the calling thread.

DF_ROOT = """Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  916G  123G  744G  15% /
"""

DF_HOME = """Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  916G   11G  744G   2% /home
"""

DF_VAR = """Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p3   50G  8.2G   40G  18% /var
"""

FREE_H = """               total        used        free      shared  buff/cache   available
Mem:           31Gi       6.2Gi        12Gi       210Mi        13Gi        24Gi
Swap:          8.0Gi      128Mi       7.9Gi
"""

LSPCI = """00:02.0 VGA compatible controller: Intel Corporation Alder Lake-P GT2 (rev 0c)
00:14.0 USB controller: Intel Corporation Alder Lake PxH USB Controller
"""

BLUETOOTHCTL_SHOW = """Controller 00:00:00:00:00:00 (public)
\tName: host
\tPowered: yes
"""

# Verbatim from power-profiles-daemon 0.22. The active profile is deliberately
# NOT last (the daemon prints power-saver, balanced, performance): a parser
# reading the list backwards would pick the wrong block, so reordering this
# fixture silently removes the only thing that lets the test fail.
PPD_GET = "balanced\n"

PPD_LIST = """  performance:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplatform_profile
    Degraded:   no

* balanced:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplatform_profile

  power-saver:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplatform_profile
"""


def _sysinfo_fakes(tmp_path, *, df_root=DF_ROOT, du="412M\t/var/log",
                   free=FREE_H, lspci=LSPCI, bluetooth=BLUETOOTHCTL_SHOW,
                   ppd_get=PPD_GET, ppd_list=PPD_LIST):
    """Fake df/du/free/lspci/bluetoothctl printing what the real ones print.

    `df -h` is answered per path, because the card asks for /, /home and /var
    separately and a test that returned one answer for all of them could not
    tell the three rows apart.
    """
    def write(name, body):
        f = tmp_path / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    # %b, not %s: the fixtures are Python reprs, so their newlines are "\n" and
    # only %b turns those back into line breaks. The fakes use printf and case
    # alone so a test can put this directory alone on PATH to test an absent
    # tool without losing cat along with it.
    paths = {"/": df_root, "/home": DF_HOME, "/var": DF_VAR}
    body = ['case "$2" in']
    for path, out in paths.items():
        body.append(f'  {path}) printf "%b" {out!r} ;;')
    body.append("esac\n")
    write("df", "\n".join(body))
    write("du", f"printf '%b\\n' {du!r}\n")
    write("free", f"printf '%b' {free!r}\n")
    write("lspci", f"printf '%b' {lspci!r}\n")
    write("bluetoothctl", f"printf '%b' {bluetooth!r}\n")
    # Answered per subcommand: the reader asks `get` for the profile in force
    # and `list` for the drivers, and a fake that printed one answer for both
    # would let a reader that only ever calls one of them pass.
    write("powerprofilesctl",
          'case "$1" in\n'
          f'  get) printf "%b" {ppd_get!r} ;;\n'
          f'  list) printf "%b" {ppd_list!r} ;;\n'
          'esac\n')
    return tmp_path


def test_the_card_parsers_read_the_tools_own_output_format():
    """The parsers on their own, with no subprocess and no main loop.

    The formats are verbatim from the tools: df's right-aligned header, free's
    two leading spaces, lspci's bus:slot.func class prefix, du's tab.
    """
    from shani_cassini import system_status as ss
    assert ss._parse_df(DF_ROOT) == "123G/916G"
    assert ss._parse_df(DF_HOME) == "11G/916G"
    assert ss._parse_free(FREE_H) == "128Mi used / 8.0Gi total"
    assert ss._parse_gpu(LSPCI) == "Intel Corporation Alder Lake-P GT2 (rev 0c)"
    assert ss._parse_bluetooth(BLUETOOTHCTL_SHOW) == "● Active"
    assert ss._parse_bluetooth("Powered: no\n") == "○ Inactive"
    # A tool that answers with a header and nothing else is not a measurement.
    assert ss._parse_df("Filesystem      Size  Used Avail Use% Mounted on\n") == ""
    assert ss._parse_free("Mem: 1Gi\n") == ""
    # `du` saying nothing used to raise IndexError out of a .split()[0]; the
    # caller's fallback is the answer for that, so the parser answers empty.
    assert ss._parse_du("") == ""
    assert ss._parse_du("412M\t/var/log\n") == "412M"


def test_the_storage_card_renders_every_row_from_the_fakes(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_sysinfo_fakes(tmp_path)}:{os.environ['PATH']}")
    from shani_cassini import system_status as ss
    out = {}
    ss.storage_card(out.update)
    assert spin(lambda: len(out) == 6), out
    assert out["storage-root-usage"] == "123G/916G"
    assert out["storage-root"] == "123G/916G"
    assert out["storage-home-usage"] == "11G/916G"
    assert out["storage-var-usage"] == "8.2G/50G"
    assert out["storage-varlog"] == "412M"
    assert out["storage-swap"] == "128Mi used / 8.0Gi total"


def test_the_storage_card_asks_df_once_for_the_two_root_rows(tmp_path, monkeypatch):
    """`storage-root` and `storage-root-usage` are the same read of `/`.

    They were two rows fed by two `df -h /` calls, so every open of System Info
    spawned the tool twice for one answer. The argv log is the evidence, so
    this counts the invocations rather than trusting the row values: two equal
    values prove nothing about how many times the tool ran.
    """
    log = tmp_path / "df.log"
    fakes = _sysinfo_fakes(tmp_path)
    dff = fakes / "df"
    body = dff.read_text().replace("esac\n", f'esac\necho "$@" >> {log}\n')
    dff.write_text(body)
    monkeypatch.setenv("PATH", f"{fakes}:{os.environ['PATH']}")
    from shani_cassini import system_status as ss
    out = {}
    ss.storage_card(out.update)
    assert spin(lambda: len(out) == 6), out
    calls = log.read_text().splitlines()
    assert calls.count("-h /") == 1, f"df -h / ran {calls.count('-h /')}x: {calls}"
    assert calls.count("-h /home") == 1, calls


def test_the_hardware_card_renders_its_tool_backed_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_sysinfo_fakes(tmp_path)}:{os.environ['PATH']}")
    from shani_cassini import system_status as ss
    out = {}
    ss.hardware_card(out.update)
    assert spin(lambda: len(out) == 8), out
    assert out["hw-gpu"] == "Intel Corporation Alder Lake-P GT2 (rev 0c)"
    assert out["hw-bluetooth"] == "● Active"


def test_one_missing_source_does_not_blank_the_other_rows(tmp_path, monkeypatch):
    """The per-row independence contract, on the async path.

    `du` is absent while df and free answer. Every row must still be filled:
    a card that shows four rows and two blanks is the failure this whole
    per-reader split exists to prevent, and the async rewrite is exactly where
    a shared error handler could quietly reintroduce it.
    """
    fakes = _sysinfo_fakes(tmp_path)
    (fakes / "du").unlink()
    # PATH is fakes ALONE, not prepended: prepending would still find this
    # host's real du and answer with this machine's /var/log size, which is the
    # same mistake a passing test would make here.
    monkeypatch.setenv("PATH", str(fakes))
    from shani_cassini import system_status as ss
    out = {}
    ss.storage_card(out.update)
    assert spin(lambda: len(out) == 6), out
    assert out["storage-varlog"] == "N/A", out
    assert out["storage-root"] == "123G/916G", out
    assert out["storage-swap"] == "128Mi used / 8.0Gi total", out


def test_the_cards_never_shell_out_synchronously():
    """The defect, pinned structurally, the way device.py's is.

    A grep for subprocess would miss a regression reintroduced through any
    other blocking reader, so this reads the AST. run_text() is the only way a
    card may read a tool now.

    Two things this deliberately does not do, both learned the hard way in this
    file. It does not name the reader functions and check inside them: that
    version sat green while checking five functions that had been renamed out
    from under it, and a gate that inspects nothing reports nothing wrong. So
    it sweeps the whole module and allowlists the few places a synchronous
    subprocess is still deliberate, and it asserts the readers it expects are
    actually there. If you rename one, this says so instead of going quiet.
    """
    import ast
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[1] / "src/shani_cassini/system_status.py").read_text()
    tree = ast.parse(src)

    readers = ("_parse_gpu", "_parse_bluetooth", "_parse_df", "_parse_du", "_parse_free")
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    missing = [name for name in readers if name not in defined]
    assert not missing, (f"this gate inspects {readers}, and {missing} no longer exist: "
                         "it would pass without reading anything")

    # No allowlist, on purpose. has_tpm2 was one here while it was a known
    # synchronous read on a page-build path, and letting a list grow is how a
    # whole-module sweep decays into an exemption nobody re-reads. Every reader
    # in this module now collects through run_json/run_text/run_status, so any
    # subprocess call here -- under any name -- is a regression.
    blocking = ("run", "Popen", "check_output", "call", "check_call")
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Name) and call.func.id == "_run":
                bad.append(f"_run at line {call.lineno} in {node.name}()")
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr in blocking
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "subprocess"):
                bad.append(f"subprocess.{call.func.attr} at line {call.lineno} in {node.name}()")
    assert not bad, ("a System Info card blocks the GTK main thread again: " + ", ".join(bad))


def test_the_cards_collect_through_run_text():
    """The other half: the reads went somewhere, they did not just disappear.

    A gate that only proves the absence of subprocess.run would also pass if
    someone deleted the readings outright and left every row on its fallback.
    """
    import ast
    from pathlib import Path as _P
    tree = ast.parse((_P(__file__).resolve().parents[1]
                      / "src/shani_cassini/system_status.py").read_text())
    cards = ("hardware_card", "storage_card")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in cards:
            called = {c.func.id for c in ast.walk(node)
                      if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            assert "_gather" in called, f"{node.name}() no longer fans its reads out"
    # _gather is the fan-out, so the tool reads are named there, not in the cards
    gather = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_gather")
    used = {c.func.id for c in ast.walk(gather)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "run_text" in used, "_gather does not read through run_text()"


# --- fprintd, over its own D-Bus API --------------------------------------
#
# fprintd is not a CLI Cassini runs and it is not activatable in CI, so the
# fake is the *bus*: only _system_bus is replaced, which leaves the real
# _dbus_call, the real argument marshalling and the real signal subscription
# to run and be checked. The answers and the method names are the ones in the
# daemon's own interface description (net.reactivated.Fprint.{Manager,
# Device}.xml) and its reference client utils/enroll.c.

DEVICE_PATH = "/net/reactivated/Fprint/device/0"
FINGER = "right-index-finger"
FPRINTD_BUS = "net.reactivated.Fprint"
NO_REPLY = ("GDBus.Error:org.freedesktop.DBus.Error.NoReply: Did not receive a reply")
DAEMON_GONE = ("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: "
               "The name net.reactivated.fprint was not provided by any .service files")
NO_ENROLLED = "net.reactivated.Fprint.Error.NoEnrolledPrints"

# The five properties the Device interface has, and the ten methods it has.
REAL_PROPERTIES = {"name", "num-enroll-stages", "scan-type", "finger-present", "finger-needed"}
REAL_METHODS = {"GetDevices", "GetDefaultDevice", "ListEnrolledFingers", "DeleteEnrolledFingers",
                "DeleteEnrolledFingers2", "DeleteEnrolledFinger", "Claim", "Release",
                "VerifyStart", "VerifyStop", "EnrollStart", "EnrollStop"}
# GetAll/Get/Set live on the standard Properties interface, not on the Device one
PROPERTIES_METHODS = {"GetAll", "Get", "Set"}
ALLOWED_METHODS = REAL_METHODS | PROPERTIES_METHODS

_NO_REPLY_SENTINEL = object()


class _Reply:
    """A D-Bus reply body already unpacked: a{sv} and as arrive as plain Python."""

    def __init__(self, value):
        self._value = value

    def unpack(self):
        return self._value


class _Message:
    def __init__(self, value):
        self._reply = _Reply(value)

    def get_reply(self):
        return self._reply


class _RemoteFailed:
    """A D-Bus error carrying one of fprintd's own error names."""

    def __init__(self, name):
        self._name = name

    def get_reply(self):
        raise GLib.Error(f"GDBus.Error:{self._name}: fprintd refused")


class FakeFprintd:
    """The daemon side of the fake bus, answering the real interface."""

    def __init__(self, devices=(DEVICE_PATH,), props=None, fingers=(FINGER,)):
        self.devices = list(devices)
        self.props = {"name": "Goodix capacitive", "num-enroll-stages": 5, "scan-type": "swipe",
                      "finger-present": False, "finger-needed": True} if props is None else props
        self.fingers = list(fingers)
        self.bus_error = ""        # set to fail the bus itself
        self.call_error = ()       # (iface, method) that must fail
        self.silent = False        # answer nothing: a daemon that hung
        self.no_enrolled = False   # raise NoEnrolledPrints instead of a list

    def answer(self, path, iface, method, params):
        if self.bus_error:
            return _RemoteFailed(self.bus_error)
        if self.silent:
            return _NO_REPLY_SENTINEL
        if (iface, method) in self.call_error:
            return _RemoteFailed("net.reactivated.Fprint.Error.Internal")
        if method == "GetDevices":
            return _Message(self.devices)
        if method == "GetAll":
            return _Message([self.props])
        if method == "ListEnrolledFingers":
            if self.no_enrolled:
                return _RemoteFailed(NO_ENROLLED)
            return _Message([self.fingers])
        return _Message([])       # the seven methods that return nothing


class FakeBus:
    """Stands in for the system bus connection.

    It records every call with the arguments exactly as Cassini marshalled
    them, so a wrong signature is caught here instead of by a live daemon,
    and it can deliver the device's signals."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.calls = []      # (destination, path, iface, method, params, reply_type, flags)
        self.subs = {}       # id -> (sender, iface, member, path, callback)

    # Gio.DBusConnection.call
    def call(self, destination, path, iface, method, params, reply_type, flags, timeout,
             cancellable, callback):
        self.calls.append((destination, path, iface, method, params, reply_type, flags))
        answer = self.daemon.answer(path, iface, method, params)
        if answer is not _NO_REPLY_SENTINEL:
            GLib.idle_add(callback, self, answer, None)
        return None

    def call_finish(self, task):
        return task

    # Gio.DBusConnection.signal_subscribe / signal_unsubscribe
    def signal_subscribe(self, sender, iface, member, object_path, arg0, flags, callback):
        sid = len(self.subs) + 1
        self.subs[sid] = (sender, iface, member, object_path, callback)
        return sid

    def signal_unsubscribe(self, sid):
        self.subs.pop(sid, None)

    def emit_enroll_status(self, reason, done):
        params = GLib.Variant("(sb)", (reason, done))
        for _sid, (_sender, _iface, member, path, cb) in list(self.subs.items()):
            if member == "EnrollStatus":
                cb(self, FPRINTD_BUS, member, path, params)

    # --- what the test asserts on -----------------------------------------
    def methods(self, mark=0):
        return [c[3] for c in self.calls[mark:]]

    def mark(self):
        """Where the enrollment's own calls begin, for methods(mark)."""
        return len(self.calls)

    def calls_since(self, mark):
        return self.calls[mark:]

    def of(self, method):
        return next(c for c in self.calls if c[3] == method)

    def args_of(self, method):
        return self.of(method)[4]


def _drain(limit: int = 200) -> None:
    """Run whatever the main loop has queued, without waiting on timers."""
    ctx = GLib.MainContext.default()
    for _ in range(limit):
        if not ctx.pending():
            return
        ctx.iteration(False)


def _refusing_bus(ready, _err) -> None:
    """A _system_bus stand-in that never hands out a connection."""
    GLib.idle_add(ready, None, "no bus in this test's teardown")


@pytest.fixture
def fake_fprintd(monkeypatch):
    from shani_cassini import system_status as ss
    # Anything a *previous* test left queued runs before this test's bus
    # exists, so a late callback cannot land in this test's call list.
    _drain()
    bus = FakeBus(FakeFprintd())
    monkeypatch.setattr(ss, "_system_bus", lambda ready: GLib.idle_add(ready, bus, ""))
    bus.fprintd_installed = lambda: True
    monkeypatch.setattr(ss, "fprintd_installed", bus.fprintd_installed)
    yield bus
    # A tab still enrolling when the test ends would otherwise call Release
    # on the *next* test's fake bus, which is how a real close-down turns
    # into a phantom "Release" with no Claim before it. Quarantine the module
    # and drain here, so those late callbacks land in this teardown.
    monkeypatch.setattr(ss, "_system_bus", _refusing_bus)
    _drain()


# --- the probe ---------------------------------------------------------------

def test_fprintd_status_reads_the_reader_and_its_fingers(fake_fprintd):
    from shani_cassini import system_status as ss
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert err == ""
    assert status["daemon"] is True and status["device_present"] is True
    assert status["name"] == "Goodix capacitive"
    assert status["scan_type"] == "swipe"
    assert status["num_enroll_stages"] == 5
    assert status["path"] == DEVICE_PATH
    assert status["fingers"] == [FINGER]
    # GetDevices on the Manager, then GetAll and ListEnrolledFingers on the
    # device path it returned
    assert fake_fprintd.methods() == ["GetDevices", "GetAll", "ListEnrolledFingers"]
    assert fake_fprintd.of("GetAll")[1] == DEVICE_PATH
    assert fake_fprintd.of("GetAll")[2] == "org.freedesktop.DBus.Properties"
    assert fake_fprintd.of("ListEnrolledFingers")[1] == DEVICE_PATH
    assert fake_fprintd.of("ListEnrolledFingers")[2] == "net.reactivated.Fprint.Device"


def test_fprintd_calls_carry_the_real_signatures(fake_fprintd):
    """The XML's signatures, checked on the marshalled arguments: a body that
    is not the declared tuple is rejected by the daemon as InvalidArgs."""
    from gi.repository import Gio
    from shani_cassini import system_status as ss
    ss.fprintd_status(lambda st, err: None)
    assert spin(lambda: fake_fprintd.methods() == ["GetDevices", "GetAll", "ListEnrolledFingers"])
    for call in fake_fprintd.calls:
        assert call[0] == FPRINTD_BUS, "must be addressed to fprintd's own bus name"
        assert call[6] == Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, \
            "without this fprintd cannot raise polkit's dialog"
    # GetDevices() and GetAll take none; the reply is a single value
    assert fake_fprintd.args_of("GetDevices").get_type_string() == "()"
    assert fake_fprintd.args_of("GetAll").get_type_string() == "(s)"
    assert fake_fprintd.args_of("GetAll").unpack() == ("net.reactivated.Fprint.Device",)
    for method in ("GetDevices", "GetAll", "ListEnrolledFingers"):
        assert fake_fprintd.of(method)[5].dup_string() == "(v)", f"{method} returns one value"
    # ListEnrolledFingers(s username): the empty string means the caller
    username = fake_fprintd.args_of("ListEnrolledFingers")
    assert username.get_type_string() == "(s)"
    assert username.unpack() == ("",), "an empty username is the calling user"


def test_fprintd_with_no_reader_attached_is_not_a_failure(fake_fprintd):
    from shani_cassini import system_status as ss
    fake_fprintd.daemon.devices = []
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert err == ""
    assert status["daemon"] is True and status["device_present"] is False
    assert status["fingers"] == []
    assert fake_fprintd.methods() == ["GetDevices"]


def test_no_enrolled_prints_is_zero_fingers_not_a_failure(fake_fprintd):
    """fprintd raises NoEnrolledPrints for a user with no fingers; that is an
    answer, and reporting it as a failure would hide the page."""
    from shani_cassini import system_status as ss
    fake_fprintd.daemon.no_enrolled = True
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert err == "", "no enrolled prints is not an error"
    assert status is not None and status["fingers"] == []


@pytest.mark.parametrize("broken", ["bus", "call"])
def test_fprintd_never_guesses_a_state_nobody_reported(fake_fprintd, broken):
    """A daemon that is absent, or that fails the call, must be an error and
    not "no fingers": the page has to be able to say "not known"."""
    from shani_cassini import system_status as ss
    if broken == "bus":
        fake_fprintd.daemon.bus_error = DAEMON_GONE
    else:
        fake_fprintd.daemon.call_error = [(ss.FPRINTD_MANAGER, "GetDevices")]
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert status is None
    assert err, "an unreachable daemon has to say why"


def test_fprintd_status_times_out_on_a_daemon_that_hangs(fake_fprintd):
    from shani_cassini import system_status as ss
    fake_fprintd.daemon.silent = True
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)), timeout_s=1)
    assert spin(lambda: got, timeout=5.0)
    status, err = got[0]
    assert status is None
    assert "in time" in err


def test_fprintd_error_names_are_readable():
    from shani_cassini import system_status as ss
    assert ss.fprintd_error(f"GDBus.Error:{NO_ENROLLED}: no prints").endswith("NoEnrolledPrints")
    assert ss.fprintd_error("GDBus.Error:org.freedesktop.DBus.Error.NoReply: x") == ""
    assert ss.fprintd_error("") == ""


def test_enroll_status_words_are_known_or_shown_verbatim():
    from shani_cassini import system_status as ss
    assert ss.enroll_status_text("enroll-completed") == "Fingerprint stored"
    for reason in ("enroll-stage-passed", "enroll-retry-scan", "enroll-swipe-too-short",
                   "enroll-finger-not-centered", "enroll-remove-and-retry", "enroll-data-full",
                   "enroll-duplicate", "enroll-disconnected", "enroll-failed"):
        assert ss.enroll_status_text(reason) not in (reason, ""), reason
    # an unknown reason is fprintd's own word, not a guess
    assert ss.enroll_status_text("enroll-something-new") == "enroll-something-new"


def test_only_the_real_finger_names_are_offered():
    from shani_cassini import system_status as ss
    assert len(ss.FINGER_NAMES) == 10
    assert "any" not in ss.FINGER_NAMES, "EnrollStart rejects 'any'"
    assert "right-index-finger" in ss.FINGER_NAMES


def test_fprintd_is_found_in_sbin_without_it_being_on_path(tmp_path, monkeypatch):
    """Every fprintd tool is in /usr/sbin, which a desktop session's PATH does
    not have: presence must not depend on PATH."""
    from shani_cassini import system_status as ss
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    tool = sbin / "fprintd-enroll"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(sbin),))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert shutil.which("fprintd-enroll") is None
    assert ss.have_sbin("fprintd-enroll") is True
    assert ss.fprintd_installed() is True


def test_fprintd_missing_everywhere_reads_as_not_installed(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(tmp_path / "nothing"),))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert ss.have_sbin("fprintd-enroll") is False
    assert ss.fprintd_installed() is False


def test_biometrics_page_without_fprintd_still_reports_the_other_methods(monkeypatch):
    """Regression, found by screenshotting the page in a container.

    This page used to be gated on fprintd and replaced wholesale by a
    "fprintd is not installed" StatusPage. That was right while the page only
    reported fingerprints, but it now also reports the other sign-in methods,
    and the gate hid exactly those from the users who need them: someone with
    no fprintd and a dead smartcard login saw a notice about fprintd and
    nothing about the smartcard.

    So the page must build, say honestly on its own rows that fprintd is
    missing, and still list what else can and cannot sign you in. The original
    intent - never show a form that cannot work - is kept by the reader rows
    and by _set_enumerable(False), not by replacing the page.
    """
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    monkeypatch.setattr(ss, "have_sbin", lambda cmd: False)
    monkeypatch.setattr(ss, "fprintd_installed", lambda: False)

    tab = BiometricsTab()
    assert spin(lambda: "Not installed" in tab._row_daemon.get_subtitle()), \
        tab._row_daemon.get_subtitle()
    assert tab._btn_enroll.is_sensitive() is False, \
        "a form that cannot work must not be left enabled"

    # What is left is exactly the sign-in methods with no page of their own.
    # Smartcard, security keys and Kerberos each got a page, so they are
    # filtered out here rather than shown twice and left to drift apart.
    titles = _group_titles(tab._auth_group)
    assert "Face / webcam recognition" in titles, titles
    assert "Iris (eye) recognition" in titles, titles
    for gone in ("Smartcard (PIV) login", "Security key (FIDO2/U2F) login",
                 "Kerberos login"):
        assert gone not in titles, f"{gone} has a page of its own: {titles}"


def _group_titles(group):
    """Every ActionRow title under a PreferencesGroup, at any depth."""
    from gi.repository import Adw
    out = []

    def walk(widget):
        if isinstance(widget, Adw.ActionRow):
            out.append(widget.get_title())
        child = widget.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(group)
    return out


def test_finger_labels_are_readable():
    from shani_cassini.tabs.biometrics import _finger_label
    assert _finger_label("right-index-finger") == "Right Index Finger"
    assert _finger_label("") == ""


# --- the page ---------------------------------------------------------------

def test_biometrics_page_reports_a_reader_and_its_fingers(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.fingers = [FINGER, "left-thumb"]
    tab = BiometricsTab()
    assert spin(lambda: tab._row_daemon.get_subtitle() == "Running")
    assert tab._row_device.get_subtitle() == "Goodix capacitive · swipe · 5 scans per finger"
    assert tab._row_fingers.get_subtitle() == "2 enrolled"
    assert tab._btn_enroll.get_sensitive()
    assert tab._fingers_group.get_visible()
    assert _action_row_titles(tab._fingers_group) == ["Right Index Finger", "Left Thumb"]
    # fake_bin's shani-deploy says profile=gnome
    assert spin(lambda: tab._row_edition.get_title() == "This edition: gnome")
    assert "Works at the login screen" in tab._row_edition.get_subtitle()


def test_biometrics_escapes_every_string_fprintd_hands_over(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.props["name"] = "Sync & <hold> \"reader\""
    fake_fprintd.daemon.fingers = ["left-index-finger"]
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    # Adw parses the row's markup on set, so get_subtitle() gives back what a
    # person sees: the exact string fprintd sent, entities consumed as markup.
    assert tab._row_device.get_subtitle().startswith('Sync & <hold> "reader" ')
    assert "&amp;" not in tab._row_device.get_subtitle()
    # get_title() hands back the markup as stored, so this is the escaping
    # itself: the entity form can only be there because _esc() ran.
    titles = _action_row_titles(tab._fingers_group)
    assert "&amp;" not in " ".join(titles)


def test_biometrics_says_not_known_when_the_daemon_is_gone(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: "did not answer" in tab._row_device.get_subtitle())
    assert tab._row_fingers.get_subtitle().startswith("Not known")
    assert "0 enrolled" not in tab._row_fingers.get_subtitle()
    assert not tab._btn_enroll.get_sensitive()
    assert not tab._fingers_group.get_visible()


def _group_named(widget, title):
    """The Adw.PreferencesGroup whose title is `title`, found by walking the
    page. Deliberately not `tab._some_attribute`: the test is about which
    group a row lands in, not about how the page stores it."""
    from gi.repository import Adw
    out = []

    def walk(w):
        c = w.get_first_child()
        while c is not None:
            if isinstance(c, Adw.PreferencesGroup) and c.get_title() == title:
                out.append(c)
            walk(c)
            c = c.get_next_sibling()

    walk(widget)
    assert len(out) == 1, f"expected exactly one group titled {title!r}, found {len(out)}"
    return out[0]


def test_the_fingerprint_login_row_is_not_filed_under_other_sign_in_methods(
        fake_bin, fake_fprintd, tmp_path, monkeypatch):
    """pam_fprintd's own PAM wiring belongs on the fingerprint page's own
    "Where a Fingerprint Works" group.

    It used to render inside "Other ways to sign in", which put the one row
    that is about this page under a heading saying it was about something else.
    Nothing about the data was wrong - hardware_auth_status() has always
    reported it - only where it was shown.
    """
    from shani_cassini import system_status as ss
    # The row only exists if a PAM service ON THIS HOST loads pam_fprintd.so,
    # and /etc/pam.d/gdm-fingerprint is a Shanios/GNOME fact - Ubuntu ships no
    # such service. Read unmocked this test passed on the dev host and failed
    # on the Ubuntu runner with the row simply absent, so it was asserting the
    # host's PAM layout rather than the placement it is named for. The data is
    # faked here, exactly as the sibling tests in this file already do it, and
    # the assertions below are then about grouping alone.
    pamd = tmp_path / "pam.d"; pamd.mkdir()
    (pamd / "gdm-fingerprint").write_text("auth required pam_fprintd.so\n")
    sec = tmp_path / "security"; sec.mkdir()
    (sec / "pam_fprintd.so").write_text("")
    # _PAM_LOGIN_SERVICES is the seam that matters, not PAM_SERVICE_DIRS:
    # hardware_auth_status() gates each of its rows on
    # `os.path.exists(<the absolute path in the table>)` and never consults the
    # service-dir list for them. Patching PAM_SERVICE_DIRS alone leaves the
    # literal /etc/pam.d/gdm-fingerprint in play, which is present on this host
    # and absent on the Ubuntu runner - the whole reason this test was flaky.
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES",
                        ((str(pamd / "gdm-fingerprint"), "Fingerprint login",
                          "pam_fprintd.so"),))
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", (str(sec),))

    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._auth_group.get_visible())

    where = _group_named(tab, "Where a Fingerprint Works")
    other = _group_named(tab, "Other ways to sign in")

    where_titles = _action_row_titles(where)
    other_titles = _action_row_titles(other)

    # the fingerprint login wiring is on the fingerprint page's own group
    assert any("Fingerprint login" in t for t in where_titles), where_titles
    # and is nowhere near the "other methods" group
    assert not any("Fingerprint" in t for t in other_titles), other_titles
    # the methods that genuinely have nowhere else to go are still there
    assert any("Face" in t for t in other_titles), other_titles


def test_the_finger_picker_offers_only_fingers_that_are_not_enrolled_yet(
        fake_bin, fake_fprintd):
    """Enrolling a finger that is already enrolled is a dead end, so the picker
    must not offer it.

    Plasma splits the list for exactly this reason
    (`availableFingersToEnroll()` / `unavailableFingersToEnroll()`); this page
    offered all ten regardless, so a user could pick one that is already
    stored. Re-enrolling is not what the user meant.
    """
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.fingers = ["right-index-finger", "left-thumb"]
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "2 enrolled")

    assert "right-index-finger" not in tab._offered
    assert "left-thumb" not in tab._offered
    assert len(tab._offered) == 8, tab._offered
    # the selection the button will act on is one of the offered ones
    assert tab._chosen_finger() in tab._offered


def test_enrolling_every_finger_is_reported_rather_than_left_with_an_empty_picker(
        fake_bin, fake_fprintd):
    """All ten enrolled is a real state, and the page has to say so instead of
    handing back a picker with nothing in it."""
    from shani_cassini.tabs.biometrics import BiometricsTab
    from shani_cassini import system_status as ss
    fake_fprintd.daemon.fingers = list(ss.FINGER_NAMES)
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "10 enrolled")

    assert tab._offered == []
    assert not tab._btn_enroll.get_sensitive()
    assert "every finger" in tab._row_enroll.get_subtitle().lower()


def test_a_second_reader_is_counted_rather_than_silently_dropped(fake_bin, fake_fprintd):
    """GetDevices can return more than one path and the page was taking
    paths[0] with no word about the rest.

    Two readers is a real configuration - a built-in sensor plus a USB one -
    and reporting one of them is a wrong answer, not a partial one. The count
    is what makes it honest; the page still drives the first, which is the one
    a scan would land on.
    """
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.devices = (DEVICE_PATH, "/net/reactivated/Fprint/Device/second")
    tab = BiometricsTab()
    assert spin(lambda: "2 readers" in tab._row_device.get_subtitle())


def test_one_reader_is_not_announced_as_a_count(fake_bin, fake_fprintd):
    """The count is only interesting when it is surprising."""
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    assert "readers" not in tab._row_device.get_subtitle()


def test_enrollment_shows_a_progress_bar_that_tracks_the_stages(fake_fprintd, fake_bin):
    """fprintd reports how many scans a finger needs and signals each one.

    We rendered that as "(2/5)" inside a subtitle, which is a number
    pretending to be a progress indicator. Plasma computes a fraction
    (`enrollProgress()`) and drives a real bar, and the fraction is the part
    a glance actually uses. Both stay: the count is worth reading, the bar is
    worth seeing.
    """
    from gi.repository import Gtk
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab, _mark = _enrolling_tab(fake_bin, fake_fprintd)
    bar = tab._progress
    assert isinstance(bar, Gtk.ProgressBar)
    assert bar.get_visible()
    assert bar.get_fraction() == 0.0
    assert bar.get_text() == "0/5"

    tab._on_enroll_status("enroll-stage-passed", False)
    tab._on_enroll_status("enroll-stage-passed", False)
    assert bar.get_fraction() == pytest.approx(2 / 5)
    assert bar.get_text() == "2/5"

    tab._on_enroll_status("enroll-completed", True)
    assert not bar.get_visible()


def test_no_progress_bar_when_the_reader_does_not_say_how_many_stages(fake_fprintd, fake_bin):
    """A device that reports no num-enroll-stages must not be given a bar
    that would have to invent a total."""
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.props["num-enroll-stages"] = None
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    assert not tab._progress.get_visible()


def test_biometrics_names_the_package_when_fprintd_is_missing(fake_bin, fake_fprintd, monkeypatch):
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    monkeypatch.setattr(ss, "fprintd_installed", lambda: False)
    fake_fprintd.daemon.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: "Not installed" in tab._row_daemon.get_subtitle())
    assert "shani-peripherals" in tab._row_daemon.get_subtitle()


def test_biometrics_will_not_enroll_on_a_reader_that_is_not_there(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.devices = []
    tab = BiometricsTab()
    assert spin(lambda: tab._row_device.get_subtitle().startswith("No reader"))
    assert "Not known" in tab._row_fingers.get_subtitle()
    assert not tab._btn_enroll.get_sensitive()
    tab._start_enroll()
    assert "Claim" not in fake_fprintd.methods()
    assert tab._enroll is None


def _enrolling_tab(fake_bin, fake_fprintd):
    """A tab with a reader, driven to the point where EnrollStart has run.

    Returns (tab, mark): the page refreshes the reader before it can enroll,
    so fake_fprintd.methods(mark) is the enrollment's own calls and nothing
    before them - read it after the run, not now, so the close-down counts."""
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    mark = fake_fprintd.mark()
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["started"])
    return tab, mark


def test_enrollment_claims_before_it_starts(fake_fprintd, fake_bin):
    """EnrollStart's own doc says the device must be claimed first, and it
    fails with ClaimDevice if it is not."""
    _tab, mark = _enrolling_tab(fake_bin, fake_fprintd)
    methods = fake_fprintd.methods(mark)
    assert methods.index("Claim") < methods.index("EnrollStart")
    assert methods[0] == "Claim", "the claim is the enrollment's first call"
    assert "EnrollStatus" in [s[2] for s in fake_fprintd.subs.values()], \
        "the signal must be watched, and before EnrollStart returns"


def test_enrollment_calls_the_real_methods_with_the_real_arguments(fake_fprintd, fake_bin):
    from gi.repository import Gio
    from shani_cassini import system_status as ss
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    claim = fake_fprintd.args_of("Claim")
    assert claim.get_type_string() == "(s)" and claim.unpack() == ("",)
    start = fake_fprintd.args_of("EnrollStart")
    assert start.get_type_string() == "(s)"
    finger = start.unpack()[0]
    assert finger in ss.FINGER_NAMES, "a finger name from the ten, not a nickname"
    assert finger != FINGER, "the finger fprintd already has stored must not be offered"
    for method in ("Claim", "EnrollStart"):
        call = fake_fprintd.of(method)
        assert call[1] == DEVICE_PATH and call[2] == "net.reactivated.Fprint.Device"
        assert call[5] is None, f"{method} returns nothing: reply_type must be None"
        assert call[6] == Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION
    # no method outside the interface the XML lists, and no bare per-scan Enroll
    assert not (set(fake_fprintd.methods()) - ALLOWED_METHODS)
    assert "Enroll" not in fake_fprintd.methods()
    assert "Delete" not in fake_fprintd.methods()
    tab.cancel_enroll()


def test_enrollment_subscribes_to_enroll_status_on_the_device(fake_fprintd, fake_bin):
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    sender, iface, member, path, _cb = list(fake_fprintd.subs.values())[0]
    assert sender == FPRINTD_BUS
    assert iface == "net.reactivated.Fprint.Device"
    assert member == "EnrollStatus"
    assert path == DEVICE_PATH
    tab.cancel_enroll()


def test_enroll_status_signals_drive_the_progress(fake_fprintd, fake_bin):
    from shani_cassini import system_status as ss
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    fake_fprintd.emit_enroll_status("enroll-retry-scan", False)
    assert tab._row_enroll.get_subtitle() == "Scan not accepted - try again"
    fake_fprintd.emit_enroll_status("enroll-stage-passed", False)
    # the stage count comes from the num-enroll-stages property (5 in the fake)
    assert "(1/5)" in tab._row_enroll.get_subtitle()
    assert "Scan stored" in tab._row_enroll.get_subtitle()
    # finger-present / finger-needed are real properties, read as it goes
    assert spin(lambda: "waiting for a finger" in tab._row_enroll.get_subtitle())
    fake_fprintd.daemon.props["finger-present"] = True
    fake_fprintd.emit_enroll_status("enroll-stage-passed", False)
    assert spin(lambda: "finger detected" in tab._row_enroll.get_subtitle())
    assert ss.enroll_status_text("enroll-stage-passed") in tab._row_enroll.get_subtitle()
    tab.cancel_enroll()


def test_a_finished_enrollment_stops_the_scans_and_releases_the_reader(fake_fprintd, fake_bin):
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    fake_fprintd.emit_enroll_status("enroll-completed", True)
    assert spin(lambda: "Release" in fake_fprintd.methods())
    methods = fake_fprintd.methods()
    assert methods.index("EnrollStop") < methods.index("Release"), \
        "the scans must be stopped before the reader is given back"
    assert fake_fprintd.args_of("EnrollStop").get_type_string() == "()"
    assert fake_fprintd.args_of("Release").get_type_string() == "()"
    assert tab._enroll is None
    assert not tab._btn_cancel.get_visible()
    assert fake_fprintd.subs == {}, "the signal subscription must be dropped"


def test_a_failed_enrollment_still_stops_and_releases(fake_fprintd, fake_bin):
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    fake_fprintd.emit_enroll_status("enroll-failed", True)
    assert spin(lambda: "Release" in fake_fprintd.methods())
    assert "EnrollStop" in fake_fprintd.methods()
    assert tab._enroll is None
    assert fake_fprintd.subs == {}


def test_cancelling_enrollment_stops_the_scans_and_releases(fake_fprintd, fake_bin):
    """A reader left mid-enrollment stays claimed and unusable, so cancel goes
    through the same close-down as a finished run."""
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    tab.cancel_enroll()
    assert spin(lambda: "Release" in fake_fprintd.methods())
    assert "EnrollStop" in fake_fprintd.methods()
    assert tab._enroll is None
    assert fake_fprintd.subs == {}
    # a late signal after cancel must do nothing at all
    fake_fprintd.emit_enroll_status("enroll-completed", True)
    spin(lambda: False, timeout=0.2)
    assert fake_fprintd.subs == {}
    assert fake_fprintd.methods().count("EnrollStop") == 1


def test_enrollment_gives_up_after_its_timeout(fake_fprintd, fake_bin):
    tab, _calls = _enrolling_tab(fake_bin, fake_fprintd)
    assert tab._enroll["timer"], "a hard timeout must be armed while enrolling"
    assert tab._enroll_deadline() is False
    assert spin(lambda: "Release" in fake_fprintd.methods())
    assert "EnrollStop" in fake_fprintd.methods()
    assert tab._enroll is None


def test_claiming_failure_is_explained_and_releases_nothing(fake_fprintd, fake_bin):
    """A Claim that fails must not be followed by a Release: the reader was
    never handed over, so there is nothing of ours to give back."""
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab

    fake_fprintd.daemon.call_error = [(ss.FPRINTD_DEVICE, "Claim")]
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    mark = fake_fprintd.mark()
    tab._start_enroll()
    assert spin(lambda: tab._enroll is None), "a refused claim must end the enrollment"
    assert fake_fprintd.methods(mark) == ["Claim"], \
        f"nothing may follow a Claim that failed: {fake_fprintd.methods(mark)}"
    assert not tab._btn_cancel.get_visible(), "no enrollment is running to cancel"
    assert fake_fprintd.subs == {}, "and no signal subscription is left open"
    # the same tab is reusable once the daemon is willing again
    fake_fprintd.daemon.call_error = []
    tab.refresh()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    mark = fake_fprintd.mark()
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["started"])
    tab.cancel_enroll()
    assert spin(lambda: "Release" in fake_fprintd.methods(mark))


def test_a_claim_refused_for_authorization_is_reported_as_a_cancelled_dialog(fake_fprintd, fake_bin):
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    fake_fprintd.daemon.call_error = [(ss.FPRINTD_DEVICE, "Claim")]
    tab._start_enroll()
    assert spin(lambda: tab._enroll is None)
    assert tab._claim_error("GDBus.Error:net.reactivated.Fprint.Error.PermissionDenied: "
                            "Not Authorized: x") == "Authorization was cancelled"
    assert tab._claim_error("GDBus.Error:x.AlreadyInUse: busy") == "Another program is using the reader"
    assert tab._start_error("GDBus.Error:x.ClaimDevice: not claimed") == \
        "fprintd did not hand over the reader"
    assert not tab._btn_cancel.get_visible()


def test_delete_asks_fprintd_for_that_finger(fake_fprintd, fake_bin):
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    tab._delete(FINGER)
    assert spin(lambda: "DeleteEnrolledFinger" in fake_fprintd.methods())
    call = fake_fprintd.of("DeleteEnrolledFinger")
    assert call[1] == DEVICE_PATH and call[2] == "net.reactivated.Fprint.Device"
    assert call[5] is None, "DeleteEnrolledFinger returns nothing"
    assert call[4].get_type_string() == "(s)"
    assert call[4].unpack() == (FINGER,), "the finger name, as ListEnrolledFingers gave it"
    assert not (set(fake_fprintd.methods()) - ALLOWED_METHODS)


def test_delete_without_a_status_deletes_nothing(fake_fprintd, fake_bin):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.daemon.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: tab._row_daemon.get_subtitle() != "Asking it…")
    tab._delete(FINGER)
    assert "DeleteEnrolledFinger" not in fake_fprintd.methods()


def test_the_page_only_ever_uses_the_real_interface(fake_fprintd, fake_bin):
    """Drive a full enroll, a delete and a refresh, then check that every
    method Cassini asked fprintd for is in the interface the XML lists."""
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["started"])
    fake_fprintd.emit_enroll_status("enroll-stage-passed", False)
    fake_fprintd.emit_enroll_status("enroll-completed", True)
    assert spin(lambda: "Release" in fake_fprintd.methods())
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    tab._delete(FINGER)
    assert spin(lambda: "DeleteEnrolledFinger" in fake_fprintd.methods())
    used = set(fake_fprintd.methods())
    assert used <= ALLOWED_METHODS, f"not in either interface: {used - ALLOWED_METHODS}"
    device_only = {c[3] for c in fake_fprintd.calls
                   if c[2] == ss.FPRINTD_DEVICE} - PROPERTIES_METHODS
    assert device_only <= REAL_METHODS, f"not a Device method: {device_only - REAL_METHODS}"
    assert "Enroll" not in used and "Delete" not in used, \
        "the per-scan Enroll() and Delete() calls do not exist in fprintd"


def test_no_invented_device_properties_are_asked_for(fake_fprintd, fake_bin):
    """The Device interface has exactly five properties; the old page read
    Action, DevicePresent, DeviceEnabled and Driver, none of which exist."""
    import inspect
    from shani_cassini import system_status
    from shani_cassini.tabs import biometrics
    src = inspect.getsource(biometrics) + inspect.getsource(system_status)
    for invented in ('"DevicePresent"', '"DeviceEnabled"', '"DeviceId"', '"Driver"', '"Action"'):
        assert invented not in src, f"{invented} is not a fprintd property"
    assert set(fake_fprintd.daemon.props) == REAL_PROPERTIES, \
        "the fake must model the five real properties, not invented ones"
    for name in ("name", "num-enroll-stages", "scan-type"):
        assert name in inspect.getsource(biometrics) or name in REAL_PROPERTIES


def _action_row_titles(group):
    """The titles of a PreferencesGroup's ActionRows, as stored (so any
    escaping of fprintd's strings is still visible)."""
    out = []

    def walk(w):
        c = w.get_first_child()
        while c is not None:
            if isinstance(c, __import__("gi").repository.Adw.ActionRow):
                out.append(c.get_title())
            walk(c)
            c = c.get_next_sibling()
    walk(group)
    return out


def test_system_bus_callback_takes_the_three_args_gobject_passes(monkeypatch):
    """Regression: Gio callbacks get (connection, result, user_data).

    A two-parameter callback raises TypeError inside GLib, which is swallowed
    and printed rather than propagated - so the fakes stayed green and only
    running against a real bus caught it. Twice. Mirroring the real arity here
    makes it a unit test. No bus is involved: Gio.bus_get/_finish are stubbed.
    """
    import inspect
    from gi.repository import Gio
    import shani_cassini.system_status as ss

    seen = {}

    def fake_get(bus_type, cancellable, callback, user_data):
        seen["arity"] = len(inspect.signature(callback).parameters)
        callback("CONNECTION", "RESULT", user_data)

    monkeypatch.setattr(Gio, "bus_get", fake_get)
    monkeypatch.setattr(Gio, "bus_get_finish", lambda res: "BUS")

    got = []
    ss._system_bus(lambda conn, err: got.append((conn, err)))
    assert seen["arity"] == 3, "Gio passes (connection, result, user_data)"
    assert got == [("BUS", "")]


def test_system_bus_reports_a_bus_failure_instead_of_raising(monkeypatch):
    """A refused bus must reach the caller as (None, message), not a traceback."""
    from gi.repository import Gio, GLib
    import shani_cassini.system_status as ss

    def fake_get(bus_type, cancellable, callback, user_data):
        callback(None, "RESULT", user_data)

    def refuse(res):
        raise GLib.Error("no system bus here")

    monkeypatch.setattr(Gio, "bus_get", fake_get)
    monkeypatch.setattr(Gio, "bus_get_finish", refuse)

    got = []
    ss._system_bus(lambda conn, err: got.append((conn, err)))
    assert got == [(None, "no system bus here")]


def test_dbus_call_callback_takes_the_three_args_gobject_passes():
    """Regression, same shape as the bus_get one: DBusConnection.call invokes
    callback(connection, result, user_data). A two-parameter lambda raises
    TypeError inside GLib, which is swallowed and printed, so the fakes stayed
    green. The visible symptom was misleading - got() then received the
    connection instead of an AsyncResult, surfacing later as
    "'DBusConnection' object has no attribute 'get_reply'".
    """
    import inspect
    import shani_cassini.system_status as ss

    seen = {}

    class FakeConn:
        def call(self, bus, path, iface, method, args, reply_type,
                 flags, timeout, cancellable, callback):
            seen["arity"] = len(inspect.signature(callback).parameters)
            callback(self, "RESULT", None)

        def call_finish(self, task):
            return task

    conn = FakeConn()
    got = []
    ss._dbus_call(conn, "/p", "i.f", "M", [],
                  lambda res, c: got.append((res, c)))
    assert seen["arity"] == 3, "DBusConnection.call passes (connection, result, user_data)"
    assert got == [("RESULT", conn)]


# --- other hardware-auth login methods -----------------------------------
#
# The bug this guards is the one that left smartcard login dead on a stock
# image: a PAM service names a module the image never shipped. PAM says
# nothing at install time, so the stack only fails when someone tries to log
# in - and a GUI that reports such a method as "unavailable" is the only place
# a user would ever find out.

def _fake_pam_tree(tmp_path, modules, services):
    """Build a fake PAM root; return (sec_dirs, service_map)."""
    sec = tmp_path / "security"
    sec.mkdir()
    for m in modules:
        (sec / m).write_text("")
    svc = tmp_path / "pam.d"
    svc.mkdir()
    smap = {}
    for name, mod in services.items():
        p = svc / name
        p.write_text(f"auth required {mod}\n")
        smap[str(p)] = mod
    return (str(sec),), smap


def _rows_by_title(rows):
    return {r["title"]: r for r in rows}


def test_pam_service_whose_module_is_missing_reports_unavailable(tmp_path, monkeypatch):
    """The real defect: the service exists, so the stack looks wired, but the
    module is absent and login can never succeed."""
    import shani_cassini.system_status as ss
    sec, smap = _fake_pam_tree(tmp_path, modules=[], services={
        "gdm-smartcard": "pam_pkcs11.so",
    })
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", sec)
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES",
                        ((p, "Smartcard (PIV) login", m) for p, m in smap.items()))

    rows = _rows_by_title(ss.hardware_auth_status())
    card = rows["Smartcard (PIV) login"]
    assert card["state"] == "unavailable"
    assert "does not ship" in card["detail"]
    assert "cannot succeed" in card["detail"]


def test_pam_service_with_its_module_installed_reports_ok(tmp_path, monkeypatch):
    import shani_cassini.system_status as ss
    sec, smap = _fake_pam_tree(tmp_path, modules=["pam_pkcs11.so"], services={
        "gdm-smartcard": "pam_pkcs11.so",
    })
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", sec)
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES",
                        ((p, "Smartcard (PIV) login", m) for p, m in smap.items()))

    rows = _rows_by_title(ss.hardware_auth_status())
    assert rows["Smartcard (PIV) login"]["state"] == "ok"
    assert "pam_pkcs11.so present" in rows["Smartcard (PIV) login"]["detail"]


def test_module_installed_but_offered_by_nothing_is_inactive(tmp_path, monkeypatch):
    """Installed is not the same as usable: with no PAM service referencing it,
    a user cannot reach it from a login screen."""
    import shani_cassini.system_status as ss
    sec, smap = _fake_pam_tree(tmp_path, modules=["pam_u2f.so"], services={})
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", sec)
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES", ())

    rows = _rows_by_title(ss.hardware_auth_status())
    key = rows["Security key (FIDO2/U2F) login"]
    assert key["state"] == "inactive"
    assert "no PAM service" in key["detail"]


def test_modalities_with_no_pam_module_are_never_reported_as_working(monkeypatch):
    """Face, iris and voice have no PAM module on Linux. If one of these ever
    reports "ok" the table is lying to the user about their hardware."""
    import shani_cassini.system_status as ss
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", ())
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES", ())

    rows = _rows_by_title(ss.hardware_auth_status())
    for title in ("Face / webcam recognition", "Iris (eye) recognition",
                  "Voice / speaker recognition",
                  "Retinal, palm, vein, gait, keystroke"):
        assert rows[title]["state"] == "unavailable", title
        assert rows[title]["module"] is None, title


def test_probe_finds_a_module_wherever_the_layout_puts_it(tmp_path, monkeypatch):
    """Regression: a single hardcoded directory made this report a working
    method as unavailable on any system with a different PAM layout, which
    tells the user their hardware is broken when it is not."""
    import shani_cassini.system_status as ss
    # Assert on the shipped list, before any patching of it.
    assert len(ss._PAM_SEC_DIRS) > 1, \
        "one directory only means a false 'unavailable' off Arch"
    sec, _ = _fake_pam_tree(tmp_path, modules=["pam_fprintd.so"], services={})
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", sec)
    assert ss._pam_module_installed("pam_fprintd.so") is True
    assert ss._pam_module_installed("pam_not_a_real_module.so") is False


def test_every_reported_state_is_one_the_renderer_knows(monkeypatch):
    """The page maps these to icons; an unmapped state would render blank."""
    import shani_cassini.system_status as ss
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", ())
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES", ())
    assert {r["state"] for r in ss.hardware_auth_status()} <= {"ok", "inactive", "unavailable"}


# --- finding the stacks that really load a module ------------------------
#
# These three cases were each found by running the scanner against a real
# /etc/pam.d and disagreeing with grep, not by reading the code. A fixture
# written from imagination passes all three wrong versions.

def test_control_field_containing_spaces_does_not_hide_the_module():
    """Real line from a stock /etc/pam.d:
        session required        pam_env.so readenv=1
    and with a bracketed control that itself contains spaces:
        auth\t[success=2 default=ignore]\tpam_unix.so nullok
    Splitting on whitespace first leaves "[success=2" and "default=ignore]"
    as separate tokens, so a fixed field index never reaches the module."""
    from shani_cassini import system_status as ss
    assert ss._pam_service_loading("session required        pam_env.so readenv=1",
                                   "pam_env.so")
    assert ss._pam_service_loading("auth\t[success=2 default=ignore]\tpam_unix.so nullok",
                                   "pam_unix.so")
    assert ss._pam_service_loading("session\toptional\tpam_systemd.so ",
                                   "pam_systemd.so")


def test_the_module_is_found_even_when_an_earlier_line_loads_another():
    """Regression: the scan returned on the first module-looking field of each
    line, so a file whose first auth line loads a different module never
    reached the line that matched. gdm-autologin hit this."""
    from shani_cassini import system_status as ss
    text = ("auth required pam_deny.so\n"
            "session required pam_env.so readenv=1\n")
    assert ss._pam_service_loading(text, "pam_env.so"), \
        "a later line must still be reached"
    assert not ss._pam_service_loading(text, "pam_pkcs11.so")


def test_a_commented_or_disabled_reference_does_not_count_as_offered():
    """A '-' prefix means present but disabled, '#' means a comment. Neither
    makes a login method usable, so neither may turn an 'inactive' row into
    'ok' - that would tell a user their key works when it cannot."""
    from shani_cassini import system_status as ss
    assert not ss._pam_service_loading("# auth sufficient pam_u2f.so\n", "pam_u2f.so")
    assert not ss._pam_service_loading("-auth\toptional\tpam_u2f.so\n", "pam_u2f.so")
    assert ss._pam_service_loading("auth sufficient pam_u2f.so\n", "pam_u2f.so")


def test_pam_stacks_loading_scans_both_service_directories(tmp_path, monkeypatch):
    """GDM's services live in /etc/pam.d, KScreenLocker's in /usr/lib/pam.d.
    Shanios also wires pam_u2f into its own system-auth override, which no
    gdm-* or kde-* file mentions - a hardcoded list called that 'not offered'
    on every machine we ship."""
    from shani_cassini import system_status as ss
    etc, lib = tmp_path / "etc", tmp_path / "lib"
    etc.mkdir(); lib.mkdir()
    (etc / "system-auth").write_text("auth sufficient pam_u2f.so\n")
    (lib / "kde-smartcard").write_text("auth required pam_pkcs11.so\n")
    monkeypatch.setattr(ss, "PAM_SERVICE_DIRS", (str(etc), str(lib)))
    assert ss.pam_stacks_loading("pam_u2f.so") == ["system-auth"]
    assert ss.pam_stacks_loading("pam_pkcs11.so") == ["kde-smartcard"]


def test_pam_stacks_loading_follows_an_include(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    d = tmp_path / "d"; d.mkdir()
    (d / "gdm-password").write_text("auth include system-auth\n")
    (d / "system-auth").write_text("auth sufficient pam_u2f.so\n")
    monkeypatch.setattr(ss, "PAM_SERVICE_DIRS", (str(d),))
    assert "pam_u2f.so" in [m for m in ("pam_u2f.so",) if ss.pam_stacks_loading(m)]


def test_pam_stacks_loading_survives_an_include_cycle(tmp_path, monkeypatch):
    """A cycle must not hang the page build."""
    from shani_cassini import system_status as ss
    d = tmp_path / "d"; d.mkdir()
    (d / "a").write_text("auth include b\n")
    (d / "b").write_text("auth include a\n")
    monkeypatch.setattr(ss, "PAM_SERVICE_DIRS", (str(d),))
    assert ss.pam_stacks_loading("pam_u2f.so") == []


def test_shanios_system_auth_makes_fido2_ok_not_inactive(tmp_path, monkeypatch):
    """The wording regression this scanner exists to fix. shani-settings ships
    etc/pam.d/system-auth with `auth sufficient pam_u2f.so`, so on every Shanios
    image a security key IS offered. The old hardcoded gdm/kde-only lookup
    reported 'installed but no PAM service on this system offers it'."""
    from shani_cassini import system_status as ss
    d = tmp_path / "pam.d"; d.mkdir()
    (d / "system-auth").write_text(
        "auth sufficient pam_u2f.so\n"
        "auth required   pam_unix.so try_first_pass nullok\n")
    # "ok" needs both halves: the module installed AND a stack that loads it.
    sec = tmp_path / "security"; sec.mkdir()
    (sec / "pam_u2f.so").write_text("")
    monkeypatch.setattr(ss, "PAM_SERVICE_DIRS", (str(d),))
    monkeypatch.setattr(ss, "_PAM_SEC_DIRS", (str(sec),))
    monkeypatch.setattr(ss, "_PAM_LOGIN_SERVICES", ())
    rows = _rows_by_title(ss.hardware_auth_status())
    key = rows["Security key (FIDO2/U2F) login"]
    assert key["state"] == "ok", key
    assert "system-auth" in key["detail"]


# --- the sign-in configuration files --------------------------------------
#
# The sign-in pages read and write the four files the login stack actually
# reads, plus the user's own pam_u2f.conf. Every save goes through
# config_io, which refuses rather than guesses, and a refusal is an exception
# there - so the whole point of this layer is that it never reaches the GTK
# main loop as one. Each test here drives a real refusal or a real write.
#
# The file contents below are the shipped formats, not invented ones: the
# subject_mapping template is what pam_pkcs11 installs, the braces conf is
# upstream's own example (every directive inside a block ends with a ';'),
# and krb5.conf keeps a tab indent and a trailing comment.

# What `make install` writes to /etc/pam_pkcs11/subject_mapping: comments and
# nothing else. Zero entries is the normal state, not a fault.
SHIPPED_MAPPING = (
    "# The subject_mapping file contains a list of certificate subject to\n"
    "# user name mappings.\n"
    "#\n"
    "# Format:\n"
    "#\n"
    "#   Certificate Subject -> user_name\n"
    "#\n"
    "# Example:\n"
    "#   \"Smartcard Certificate\" -> \"jdoe\"\n"
)

MAPPED_FILE = (
    "# the admin's card\n"
    "CN=Shani Admin,O=SHANI,C=LOCAL -> shani\n"
    "\n"
    "CN=Shani Ops,O=SHANI,C=LOCAL -> ops\n"
    "# keep this trailing comment where it is\n"
)

# A subject that itself contains an arrow: only the LAST one separates.
ARROWED_SUBJECT = "CN=Shani,OU=A->B,C=LOCAL -> shani\n"

# pam_pkcs11.conf with both mapper block forms, and a mapfile value that
# contains a '//' which is not a comment.
PKCS11_CONF = (
    "// pam_pkcs11.conf\n"
    "/* Certificate and CRL handling */\n"
    "open_ssl = /usr/bin/openssl\n"
    "use_crl = true;\n"
    "\n"
    "mapper subject { module = internal; "
    "mapfile = file:///etc/pam_pkcs11/subject_mapping; }\n"
    "\n"
    "mapper opensc {\n"
    "    module = opensc-pkcs11.so;\n"
    "    mapfile = file:///etc/pam_pkcs11/opensc_pkcs11_mapfile;\n"
    "}\n"
    "mapper openssh {\n"
    "    module = openssh;\n"
    "    mapfile = pubkey:file:///home/$USER/.ssh/authorized_keys;\n"
    "}\n"
)


# /etc/krb5.conf, in the form a save can round-trip.
KRB5_PLAIN = (
    "[libdefaults]\n"
    "\tdefault_realm = SHANI.LAN\n"
    "default_ccache_name = FILE:/tmp/krb5cc_%{uid}\n"
    "\n"
    "[domain_realm]\n"
    ".shani.lan = SHANI.LAN\n"
    "shani.lan = SHANI.LAN\n"
    "\n"
    "[realms]\n"
    " SHANI.LAN = { kdc = kdc.shani.lan }\n"
)

# The same file as a stock krb5.conf carries it: a pre-section includedir and
# a trailing comment on the realm.
KRB5_CONF = (
    "includedir /etc/krb5.conf.d\n"
    "\n"
    "[libdefaults]\n"
    "\tdefault_realm = SHANI.LAN   # the only realm here\n"
    "default_ccache_name = FILE:/tmp/krb5cc_%{uid}\n"
    "\n"
    "[domain_realm]\n"
    ".shani.lan = SHANI.LAN\n"
    "shani.lan = SHANI.LAN\n"
    "\n"
    "[realms]\n"
    " SHANI.LAN = { kdc = kdc.shani.lan }\n"
)

# pam_yubico.conf: one setting per line, a comment and a blank line.
PAM_YUBICO_CONF = (
    "# yubico settings - one setting per line\n"
    "authfile  /etc/security/pam_yubico/authorized_yubikeys\n"
    "alwaysok   off\n"
    "\n"
    "id example.com:shani.lan\n"
    "debug_file /tmp/pam.log\n"
)

# What a fake pcsc_scan prints, in pcsc-lite's own column layout.
PCSC_SCAN = (
    "Nr.  Card  Features               ATR Info            AID Info\n"
    "------------------------------------------------\n"
    " 0   Yubico YubiKey OTP+FIDO+CCID 00 00 00 00 00 00 00 00 00 00 00 00\n"
    " 1   Feitian ePass FIDO2          3b 65 00 00 81 01 81 01 81 05 00\n"
)


@pytest.fixture(autouse=True)
def config_backup_root(tmp_path, monkeypatch):
    """A save backs the original up before it writes, so BACKUP_ROOT has to
    point into this test's tmp dir - never the real user state dir."""
    from shani_cassini import config_io
    root = tmp_path / "config-backups"
    monkeypatch.setattr(config_io, "_backup_root", lambda: str(root))
    return root


@pytest.fixture
def config_pkexec(fake_bin):
    """pkexec on PATH that logs its argv and installs faithfully, so a
    privileged save is really the last two arguments copied over the target."""
    log = fake_bin / "config-pkexec.log"
    (fake_bin / "pkexec").write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> {log}\n'
        'cp "${@: -2:1}" "${@: -1}"\n'
        "exit 0\n")
    (fake_bin / "pkexec").chmod(0o755)
    return log


def _point(monkeypatch, name, tmp_path, text=None):
    """Point one of system_status's path constants at a file in tmp_path.

    The file keeps the real basename, because config_io derives the staging
    and backup file names from it.
    """
    from shani_cassini import system_status as ss
    path = tmp_path / name
    if text is not None:
        path.write_text(text)
    monkeypatch.setattr(ss, name, str(path))
    return path


@pytest.fixture
def own_config(monkeypatch):
    """These tests own the files they edit, so the engine's root-ownership
    check is satisfied by whoever runs them rather than by a chown."""
    from shani_cassini import system_status as ss
    monkeypatch.setattr(ss, "CONFIG_OWNER", None)


def _done(got):
    """A done callback that records (error, note) calls."""
    return lambda error, note: got.append((error, note))


# --- reading the files the login stack reads -------------------------------

def test_the_shipped_empty_mapping_template_is_not_a_problem(tmp_path, monkeypatch):
    """`make install` writes a comment-only subject_mapping. Reporting that as
    an unreadable file would put a fault on a system that is fine."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, SHIPPED_MAPPING)

    state = ss.subject_mappings()
    assert state["exists"] is True
    assert state["entries"] == [], "an empty template has no mappings, and says so"
    assert state["problems"] == [], "comments and blank lines are not a fault"
    assert state["path"] == str(path)


def test_a_subject_that_contains_an_arrow_splits_on_the_last_one(tmp_path, monkeypatch):
    """A DN may legally contain '->'. Splitting on the first one would file it
    under a subject of 'CN=Shani,OU=A' - a login that does not exist."""
    from shani_cassini import system_status as ss
    _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, ARROWED_SUBJECT)

    state = ss.subject_mappings()
    assert state["problems"] == []
    assert state["entries"] == [
        {"subject": "CN=Shani,OU=A->B,C=LOCAL", "login": "shani", "lineno": 0}]


def test_a_line_without_an_arrow_is_reported_and_never_written_over(own_config, tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path,
                  MAPPED_FILE + "CN=Shani Ops,O=SHANI,C=LOCAL ops\n")
    before = path.read_text()

    state = ss.subject_mappings()
    assert [(p["lineno"], p["why"]) for p in state["problems"]] == \
        [(5, "there is no '->' in it")], state["problems"]
    assert [e["login"] for e in state["entries"]] == ["shani", "ops"]

    got = []
    ss.set_mapping("CN=Shani New,C=LOCAL", "new", done=_done(got))
    assert got and got[0][1] == "", "a refusal carries no note"
    assert "line 6" in got[0][0], got[0][0]
    assert path.read_text() == before, "a file we could not read is never rewritten"


def test_setting_a_subject_that_is_already_mapped_replaces_that_line(own_config, tmp_path, monkeypatch):
    """The template has no entries, so this is the case a page hits first: the
    same certificate must not end up on two lines, and the comments around it
    must survive byte for byte."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, MAPPED_FILE)

    got = []
    ss.set_mapping("CN=Shani Ops,O=SHANI,C=LOCAL", "ops2", done=_done(got))
    assert got == [("", f"Saved {ss.SUBJECT_MAPPING}")], got

    assert path.read_text() == MAPPED_FILE.replace("-> ops", "-> ops2")
    state = ss.subject_mappings()
    assert [e["login"] for e in state["entries"]] == ["shani", "ops2"]
    assert len(state["entries"]) == 2, "the subject was replaced, not appended to"
    assert state["problems"] == []


def test_pam_pkcs11_state_reads_the_mappers_and_the_provider(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    _point(monkeypatch, "PKCS11_CONF", tmp_path, PKCS11_CONF)
    (tmp_path / "opensc-module-path").write_text("/usr/lib/opensc-pkcs11.so\n")
    monkeypatch.setattr(ss, "PKCS11_MODULE_PATH", str(tmp_path / "opensc-module-path"))
    monkeypatch.setattr(ss, "_pam_module_installed", lambda module: module == "pam_pkcs11.so")

    state = ss.pam_pkcs11_state()
    assert state["installed"] is True
    assert state["conf_exists"] is True
    assert state["provider"] == "/usr/lib/opensc-pkcs11.so"
    assert state["problems"] == []
    assert state["mappers"]["mapper subject"] == {
        "module": "internal", "mapfile": "file:///etc/pam_pkcs11/subject_mapping"}
    # a multi-line block, whose mapfile value contains a '//' that is not a comment
    assert state["mappers"]["mapper openssh"]["mapfile"] == \
        "pubkey:file:///home/$USER/.ssh/authorized_keys"
    assert set(state["mappers"]) == {"mapper subject", "mapper openssh", "mapper opensc"}


def test_pam_pkcs11_state_without_a_conf_is_a_fault_not_an_absence(tmp_path, monkeypatch):
    """The module is installed but has no configuration to use: smartcard login
    cannot work, and a page must be able to say which half is missing."""
    from shani_cassini import system_status as ss
    _point(monkeypatch, "PKCS11_CONF", tmp_path, None)
    monkeypatch.setattr(ss, "_pam_module_installed", lambda module: True)

    state = ss.pam_pkcs11_state()
    assert state["installed"] is True and state["conf_exists"] is False
    assert state["mappers"] == {}
    assert len(state["problems"]) == 1 and "is missing" in state["problems"][0]


def test_pam_yubico_config_says_when_the_file_holds_a_key_it_does_not_know(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    known = _point(monkeypatch, "PAM_YUBICO_CONF", tmp_path, PAM_YUBICO_CONF)

    conf = ss.pam_yubico_config()
    assert conf["exists"] is True and conf["known_only"] is True
    assert conf["values"] == {
        "authfile": "/etc/security/pam_yubico/authorized_yubikeys",
        "alwaysok": "off", "id": "example.com:shani.lan", "debug_file": "/tmp/pam.log"}

    # a setting this version of the module does not document must not be
    # dropped in silence
    known.write_text(PAM_YUBICO_CONF + "wibble 1\n")
    conf = ss.pam_yubico_config()
    assert conf["known_only"] is False
    assert conf["values"]["wibble"] == "1"


def test_an_absent_u2f_config_is_the_modules_defaults_not_an_error(tmp_path, monkeypatch):
    """pam_u2f falls back to its compiled-in defaults when the file is not
    there. That is an answer, and inventing values for it would be a lie."""
    from shani_cassini import system_status as ss
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-dir"))

    conf = ss.u2f_config()
    assert conf["exists"] is False
    assert conf["values"] == {}, "an absent file has no values, not default ones"
    assert conf["known_only"] is True
    assert conf["path"] == str(tmp_path / "no-such-dir" / "Yubico" / "pam_u2f.conf")


def test_u2f_config_path_follows_xdg_then_home(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert ss.u2f_conf_path() == str(tmp_path / "xdg" / "Yubico" / "pam_u2f.conf")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert ss.u2f_conf_path() == str(tmp_path / "home" / ".config" / "Yubico" / "pam_u2f.conf")


def test_u2f_config_reads_the_keys_the_module_really_has(tmp_path, monkeypatch):
    """`authfile = ...`, a presence-only flag and a `key=value` line, which is
    what pam-u2f 1.4.0's own parser accepts. touchauth and verbose are not
    settings it has, so a value for them is not a value it would read."""
    from shani_cassini import system_status as ss
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path = tmp_path / "xdg" / "Yubico" / "pam_u2f.conf"
    path.parent.mkdir(parents=True)
    path.write_text("# a comment\n"
                    "authfile = /home/shani/.config/Yubico/u2f_keys\n"
                    "appid=https://shani.dev\n"
                    "nouserok\n"
                    "interactive\n")

    conf = ss.u2f_config()
    assert conf["exists"] is True and conf["known_only"] is True
    assert conf["values"] == {"authfile": "/home/shani/.config/Yubico/u2f_keys",
                              "appid": "https://shani.dev",
                              "nouserok": "", "interactive": ""}
    assert "touchauth" not in conf["values"] and "verbose" not in conf["values"]


def test_krb5_config_reads_libdefaults_and_says_which_includes_it_skipped(tmp_path, monkeypatch):
    """default_realm only counts inside [libdefaults] - a top-level one is not
    a setting krb5.conf accepts, so it is never read as the realm."""
    from shani_cassini import system_status as ss
    _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_CONF)

    conf = ss.krb5_config()
    assert conf["exists"] is True
    assert conf["default_realm"] == "SHANI.LAN"
    assert conf["default_ccache_name"] == "FILE:/tmp/krb5cc_%{uid}"
    assert conf["domain_realm"] == {".shani.lan": "SHANI.LAN", "shani.lan": "SHANI.LAN"}
    assert conf["includes"] == ["includedir /etc/krb5.conf.d"], \
        "an include is either followed or named, never silently ignored"
    assert conf["other"] == [("realms", "SHANI.LAN", "{ kdc = kdc.shani.lan }")]
    assert conf["problems"] == []


def test_a_save_refuses_a_krb5_conf_that_includes_another_file(own_config, tmp_path, monkeypatch):
    """config_io's INI grammar has no whitespace-separated directive, so the
    includedir a stock krb5.conf carries is a line it will not write back. The
    file is left exactly as it was rather than saved with that line dropped."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_CONF)
    before = path.read_text()

    got = []
    ss.krb5_set("default_realm", "SHANI.EXAMPLE", done=_done(got))
    assert got and got[0][0] and "line 1" in got[0][0], got
    assert path.read_text() == before


# --- writing them ---------------------------------------------------------

def test_writing_the_users_own_u2f_config_never_asks_for_root(pkexec_log, tmp_path, monkeypatch):
    """~/.config/Yubico/pam_u2f.conf belongs to the user: a save here must not
    raise a polkit dialog, or every security-key setting would ask for a
    password to edit a file the user already owns."""
    from shani_cassini.config_io import parse_flat
    from shani_cassini import system_status as ss
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path = tmp_path / "xdg" / "Yubico" / "pam_u2f.conf"
    path.parent.mkdir(parents=True)
    path.write_text("# a comment\nauthfile /home/shani/old_keys\n")

    got = []
    ss.set_config_value(ss.u2f_conf_path(), "authfile", "/home/shani/new_keys",
                        parser=parse_flat, expect_owner=None, done=_done(got))
    assert got[0][0] == "", got
    assert not pkexec_log.exists(), f"pkexec ran: {pkexec_log.read_text()}"
    assert path.read_text() == "# a comment\nauthfile /home/shani/new_keys\n"
    assert list(path.parent.iterdir()) == [path], "no staging file left behind"


def test_a_file_that_is_not_ours_is_installed_through_pkexec(config_pkexec, own_config, tmp_path, monkeypatch):
    """A root config file goes through pkexec install(1), and the value travels
    in the staged file - never in argv, where anyone could read it."""
    from shani_cassini import config_io
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_PLAIN)
    # a tmp file belongs to whoever ran the tests; stage() reads the target's
    # owner to decide, so this is what makes it a root file here
    monkeypatch.setattr(config_io.os, "getuid", lambda: 0)

    got = []
    ss.krb5_set("default_realm", "SHANI.EXAMPLE", done=_done(got))
    assert got[0][0] == "", got
    argv = config_pkexec.read_text().split()
    assert argv[0] == "/usr/bin/install", argv
    assert argv[1:2] == ["-m"] and argv[3:4] == ["-o"] and argv[5:6] == ["-g"], argv
    assert argv[-1] == str(path), "the target is the last argument"
    assert argv[-2].endswith(f"{config_io.TMP_PREFIX}KRB5_CONF"), \
        f"the content comes from a staged file, not from argv: {argv[-2]}"
    assert "SHANI.EXAMPLE" not in config_pkexec.read_text(), \
        "the new value must never appear in argv"
    assert "default_realm = SHANI.EXAMPLE" in path.read_text()


def test_krb5_set_refuses_a_credential_cache_an_ordinary_login_cannot_use(own_config, tmp_path, monkeypatch):
    """KEYRING: and KCM: need a running keyring or the KCM daemon at every
    login, which is not what someone signing in at this machine gets."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_PLAIN)
    before = path.read_text()

    for value in ("KEYRING:persistent:0", "KCM:persistent:0", "DIR:/run/user/0/krb5cc"):
        got = []
        ss.krb5_set("default_ccache_name", value, done=_done(got))
        assert got and got[0][1] == "", got
        assert "login" in got[0][0], got[0][0]
        assert path.read_text() == before, f"{value} was written"


def test_krb5_set_refuses_a_realm_that_is_not_a_realm(own_config, tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_PLAIN)
    got = []
    ss.krb5_set("default_realm", "SHANI LAN", done=_done(got))
    assert got and got[0][1] == ""
    assert "SHANI.LAN" in path.read_text(), "the realm on disk is unchanged"


def test_krb5_set_writes_into_libdefaults_and_says_so(own_config, tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_PLAIN)
    got = []
    ss.krb5_set("default_realm", "SHANI.EXAMPLE", done=_done(got))
    assert got[0][0] == "", got
    assert path.read_text() == KRB5_PLAIN.replace(
        "\tdefault_realm = SHANI.LAN", "\tdefault_realm = SHANI.EXAMPLE"), \
        "the tab indent and every other line survive"
    assert ss.krb5_config()["default_realm"] == "SHANI.EXAMPLE"


def test_a_save_that_would_glue_a_comment_onto_the_value_is_refused(own_config, tmp_path, monkeypatch):
    """config_io rebuilds a line as indent+key+sep+value+tail, and the run of
    whitespace a trailing comment was separated by is in neither part, so the
    saved value would end in '# the only realm here' and krb5 would reject the
    whole file. The validator sees the glued value and refuses; nothing is
    written. Reported upstream as a config_io defect, not worked around."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_CONF)
    before = path.read_text()

    got = []
    ss.krb5_set("default_realm", "SHANI.EXAMPLE", done=_done(got))
    assert got and got[0][0], "a save that would break the file must not report success"
    assert path.read_text() == before


def test_removing_a_mapping_leaves_the_rest_of_the_file_alone(own_config, tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, MAPPED_FILE)

    got = []
    ss.remove_mapping("CN=Shani Admin,O=SHANI,C=LOCAL", done=_done(got))
    assert got[0][0] == "", got
    assert [e["login"] for e in ss.subject_mappings()["entries"]] == ["ops"]
    assert path.read_text() == MAPPED_FILE.replace(
        "CN=Shani Admin,O=SHANI,C=LOCAL -> shani\n", "\n"), path.read_text()


def test_a_certificate_that_is_not_mapped_yet_cannot_be_added(own_config, tmp_path, monkeypatch):
    """config_io's stage() refuses any document whose line count changed, and
    that is what Document.add() does - so a subject that is not in the file
    yet cannot be written through this engine at all. Reported upstream; here
    it must refuse rather than lose the line. The file is left as it was."""
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, MAPPED_FILE)
    before = path.read_text()

    got = []
    ss.set_mapping("CN=Shani New,C=LOCAL", "new", done=_done(got))
    assert got and got[0][0], "adding a line the engine cannot save must not report success"
    assert path.read_text() == before


def test_a_u2f_config_with_a_bare_flag_can_be_read_but_not_saved(tmp_path, monkeypatch):
    """`nouserok` on its own is a setting pam-u2f reads, and the reader reports
    it. parse_flat needs whitespace to find a key, so the line is one it cannot
    reproduce, and a save refuses the file rather than rewrite the flag as
    'nouserok ' - a change nobody asked for. Reported upstream."""
    from shani_cassini.config_io import parse_flat
    from shani_cassini import system_status as ss
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path = tmp_path / "xdg" / "Yubico" / "pam_u2f.conf"
    path.parent.mkdir(parents=True)
    path.write_text("authfile /home/shani/keys\nnouserok\n")
    before = path.read_text()

    assert ss.u2f_config()["values"]["nouserok"] == "", "the flag is still reported"
    got = []
    ss.set_config_value(ss.u2f_conf_path(), "authfile", "/home/shani/other",
                        parser=parse_flat, expect_owner=None, done=_done(got))
    assert got and got[0][0] and "line 2" in got[0][0], got
    assert path.read_text() == before


def test_the_keys_offered_are_the_ones_the_modules_really_have():
    """pam-u2f 1.4.0's own cfg.c has no touchauth and no verbose, and
    pam_yubico's documented list is the one above - a page must not offer a
    setting the module would ignore."""
    from shani_cassini import system_status as ss
    assert "touchauth" not in ss.U2F_KEYS and "verbose" not in ss.U2F_KEYS
    assert set(ss.U2F_KEYS) == {
        "debug", "manual", "nouserok", "openasuser", "alwaysok", "interactive",
        "cue", "nodetect", "expand", "sshformat", "authfile", "origin", "appid"}
    assert set(ss.PAM_YUBICO_KEYS) == {
        "authfile", "id", "key", "alwaysok", "try_first_pass", "use_first_pass",
        "always_prompt", "nullok", "ldap_starttls", "ldap_bind_as_user",
        "urllist", "mode", "debug", "debug_file", "chalresp_path"}


def test_the_yubico_authfile_default_is_spelled_the_way_the_file_is():
    """The mapping file is authorized_yubikeys; a page that offers the default
    path has to offer one the module can open."""
    from shani_cassini import system_status as ss
    assert ss.YUBICO_AUTHFILE_DEFAULT == "~/.yubico/authorized_yubikeys"


# --- nothing refuses by raising -------------------------------------------

def test_no_refusal_reaches_a_page_as_an_exception(own_config, tmp_path, monkeypatch):
    """ConfigRefused is how config_io says "nothing was written". A page has
    one callback and no try/except, so every refusal must arrive as
    done(message, "") - and the file must be byte for byte what it was."""
    from shani_cassini.config_io import ConfigRefused, parse_flat, parse_ini
    from shani_cassini import system_status as ss

    mapping = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, MAPPED_FILE)
    krb5 = _point(monkeypatch, "KRB5_CONF", tmp_path, KRB5_PLAIN)
    missing = tmp_path / "not-there"
    refuse = lambda text: (_ for _ in ()).throw(ValueError("no"))  # noqa: E731

    cases = [
        ("a file that is not there", lambda d: ss.set_config_value(
            str(missing), "authfile", "x", parser=parse_flat, expect_owner=None, done=d)),
        ("a key that is not there", lambda d: ss.set_config_value(
            str(krb5), "dns_lookup_kdc", "true", section="libdefaults",
            parser=parse_ini, done=d)),
        ("a file that is not the one we mean", lambda d: ss.set_config_value(
            str(krb5), "default_realm", "SHANI.EXAMPLE", section="libdefaults",
            parser=parse_ini, must_contain=("[realms]",), done=d)),
        ("a caller's own check", lambda d: ss.set_config_value(
            str(krb5), "default_realm", "SHANI.EXAMPLE", section="libdefaults",
            parser=parse_ini, done=d, validator=refuse)),
        ("a cache type no login can use", lambda d: ss.krb5_set(
            "default_ccache_name", "KEYRING:persistent:0", done=d)),
        ("a realm that is not a realm", lambda d: ss.krb5_set(
            "default_realm", "not a realm", done=d)),
        ("an empty login name", lambda d: ss.set_mapping("CN=A,C=LOCAL", "  ", done=d)),
        ("an empty certificate subject", lambda d: ss.set_mapping("", "shani", done=d)),
        ("an arrow inside the subject", lambda d: ss.set_mapping(
            "CN=A->B,C=LOCAL", "shani", done=d)),
        ("an arrow inside the login", lambda d: ss.set_mapping(
            "CN=A,C=LOCAL", "a->b", done=d)),
        ("a subject that is not mapped", lambda d: ss.set_mapping(
            "CN=Nobody,C=LOCAL", "shani", done=d)),
        ("a mapping to remove that is not there", lambda d: ss.remove_mapping(
            "CN=Nobody,C=LOCAL", done=d)),
    ]
    for why, call in cases:
        got = []
        try:
            call(_done(got))
        except ConfigRefused as escaped:
            raise AssertionError(f"{why} escaped as an exception: {escaped}")
        assert got, f"{why} never called done()"
        assert got[0][0], f"{why} reported success: {got}"
        assert got[0][1] == "", f"{why} carried a note on a refusal: {got}"
    assert mapping.read_text() == MAPPED_FILE
    assert krb5.read_text() == KRB5_PLAIN


def test_a_mapping_write_refuses_a_file_with_a_line_it_cannot_read(own_config, tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    path = _point(monkeypatch, "SUBJECT_MAPPING", tmp_path, MAPPED_FILE + "no arrow here\n")
    before = path.read_text()

    got = []
    ss.set_mapping("CN=Shani Ops,O=SHANI,C=LOCAL", "ops2", done=_done(got))
    assert got and got[0][0] and "line 6" in got[0][0], got
    assert path.read_text() == before


def test_no_reader_raises_on_a_file_that_is_not_there(tmp_path, monkeypatch):
    """A missing config file is a state the pages must render, not a traceback:
    'this system has none of these' is an answer, not a failure."""
    from shani_cassini import system_status as ss
    for name in ("PKCS11_CONF", "SUBJECT_MAPPING", "PAM_YUBICO_CONF", "KRB5_CONF"):
        _point(monkeypatch, name, tmp_path, None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert ss.subject_mappings()["exists"] is False
    assert ss.subject_mappings()["entries"] == []
    assert ss.krb5_config()["exists"] is False
    assert ss.krb5_config()["default_realm"] == ""
    assert ss.pam_yubico_config()["exists"] is False
    assert ss.pam_pkcs11_state()["problems"], "a module with no conf is a fault"


# --- the smartcard readers, through pcsc_scan ------------------------------
#
# pcsc-lite's own tool, the one the Fingerprint page already tells the user to
# run by hand. It is the only thing here that talks to the reader daemon, and
# it needs no root, so the reader list must never raise a polkit dialog.

def _bin(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def test_pcsc_readers_lists_what_pcsc_scan_prints(fake_bin):
    from shani_cassini import system_status as ss
    _bin(fake_bin, "pcsc_scan",
         f"cat <<'EOF'\n{PCSC_SCAN}EOF\nexit 0\n")

    got = []
    ss.pcsc_readers(lambda readers, error: got.append((readers, error)))
    assert spin(lambda: got), "pcsc_readers never called back"
    readers, error = got[0]
    assert error == ""
    assert [r["nr"] for r in readers] == [0, 1]
    # pcsc-lite prints the card name in a free-text column, so a card may be
    # two words: everything after the number is reported, not guessed apart
    assert readers[0]["text"].startswith("Yubico YubiKey OTP+FIDO+CCID ")
    assert readers[1]["text"].startswith("Feitian ePass FIDO2 ")


def test_pcsc_scan_failing_is_reported_rather_than_shown_as_no_reader(fake_bin):
    """An empty list means no reader. A pcsc_scan that failed means nobody
    answered, and a page must be able to say which of the two it is."""
    from shani_cassini import system_status as ss
    _bin(fake_bin, "pcsc_scan",
         "echo 'SCardEstablishContext: Resource temporarily unavailable' >&2\nexit 1\n")

    got = []
    ss.pcsc_readers(lambda readers, error: got.append((readers, error)))
    assert spin(lambda: got)
    readers, error = got[0]
    assert readers is None, "a failure is not an empty list"
    assert "SCardEstablishContext" in error, error


def test_pcsc_scan_with_no_reader_attached_is_an_empty_list(fake_bin):
    from shani_cassini import system_status as ss
    _bin(fake_bin, "pcsc_scan",
         "echo 'Nr.  Card  Features               ATR Info            AID Info'\n"
         "echo '------------------------------------------------'\nexit 0\n")

    got = []
    ss.pcsc_readers(lambda readers, error: got.append((readers, error)))
    assert spin(lambda: got)
    assert got[0] == ([], "")

# --- shani-health --storage-info -----------------------------------------
#
# The fixture below is the REAL captured output of
# `shani-health --storage-info --json` from a Btrfs Shanios layout, not
# something written to match the parser. That is the point: the flag's shape is
# nothing like its name suggests, and an invented fixture would agree with
# whatever the parser was written to expect.
REAL_STORAGE_INFO = '{"timestamp":"2026-09-26T10:13:21+00:00","checks":[{"section":"","key":"Free","status":"warning","message":" 11.3 GB — getting low"},{"section":"","key":"Quotas","status":"ok","message":"consistent"},{"section":"","key":"Scrub tmr","status":"critical","message":"btrfs-scrub.timer not enabled"},{"section":"","key":"Scrub","status":"info","message":"no scrub recorded yet"},{"section":"","key":"Maint tmrs","status":"critical","message":"all not enabled: balance defrag trim"},{"section":"","key":"bees","status":"info","message":"not configured (run beesd-setup to enable dedup)"},{"section":"","key":"Dev errors","status":"ok","message":"all zero"},{"section":"","key":"Total","status":"info","message":"12.00GiB"},{"section":"","key":"Used","status":"info","message":"82.68MiB"},{"section":"","key":"@blue","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@containers","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@data","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@green","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@home","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@nix","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@swap","status":"info","message":"?"},{"section":"","key":"@waydroid","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@blue_backup_20260820090000","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@green_backup_20260924120000","status":"info","message":"960K (ratio: 16M)"},{"section":"","key":"@cache","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@flatpak","status":"info","message":"36K (ratio: 888K)"},{"section":"","key":"@libvirt","status":"info","message":"?"},{"section":"","key":"@log","status":"info","message":"?"},{"section":"","key":"@lxc","status":"info","message":"?"},{"section":"","key":"@lxd","status":"info","message":"?"},{"section":"","key":"@machines","status":"info","message":"?"},{"section":"","key":"@qemu","status":"info","message":"?"},{"section":"","key":"@root","status":"info","message":"?"},{"section":"","key":"@snapd","status":"info","message":"?"},{"section":"","key":"Flatpak","status":"info","message":"8 MB  (0 apps, 0 runtimes)"},{"section":"","key":"Snapshots","status":"info","message":"6 total"},{"section":"","key":"Dedup","status":"info","message":"duperemove not installed — cross-slot deduplication unavailable"},{"section":"","key":"bees","status":"info","message":"not configured (run beesd-setup to enable dedup)"}]}\n'


def _storage(monkeypatch, payload, error=""):
    from shani_cassini import system_status as ss
    got = []
    if error:
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(None, error))
    else:
        import json
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(json.loads(payload), ""))
    ss.storage_info(got.append)
    assert got, "storage_info never called back"
    return got[0]


def test_storage_info_reads_the_real_captured_output(monkeypatch):
    """Every claim below was read off the captured file, not the help text."""
    out = _storage(monkeypatch, REAL_STORAGE_INFO)
    assert out["ok"] and out["problem"] == ""
    assert out["timestamp"], "the payload carries a timestamp"
    # Sizes are human strings, and the figure after "ratio:" is the
    # UNCOMPRESSED size - not a compression ratio.
    blue = [s for s in out["subvolumes"] if s["name"] == "@blue"]
    assert blue and blue[0]["used"] == "960K", blue
    assert blue[0]["uncompressed"] == "16M", blue
    # Total is a string from `btrfs filesystem usage`, not a number.
    assert out["summary"]["Total"]["message"] == "12.00GiB", out["summary"]["Total"]
    # A leading space survives in the raw message; the summary strips it.
    assert out["summary"]["Free"]["message"].startswith("11.3 GB"), out["summary"]["Free"]
    # Snapshots counts @blue and @green too, because they are snapshots.
    assert out["summary"]["Snapshots"]["message"] == "6 total"


def test_storage_info_separates_warnings_from_the_rest(monkeypatch):
    out = _storage(monkeypatch, REAL_STORAGE_INFO)
    assert out["warnings"], "the captured run has warnings (Free space, timers)"
    assert all(w["status"] in ("warning", "critical", "fail")
               for w in out["warnings"]), out["warnings"]
    assert any(w["key"] == "Free" for w in out["warnings"]), out["warnings"]


def test_storage_info_reports_a_missing_binary_instead_of_raising(monkeypatch):
    """A page that raises during build renders blank; ok=False with a reason
    is the only version a user can do anything with."""
    out = _storage(monkeypatch, "", error="shani-health is not installed")
    assert out["ok"] is False
    assert "not installed" in out["problem"]
    assert out["summary"] == {} and out["subvolumes"] == []


def test_storage_info_reports_malformed_json_instead_of_raising(monkeypatch):
    """The real risk: _print_json builds the document by string concatenation
    and _json_escape only escapes backslash and double-quote, so a message
    containing a newline yields invalid JSON. The shared run_json reports that
    as an error and this must pass it through, not swallow it."""
    out = _storage(monkeypatch, "", error="Expecting value: line 1 column 1")
    assert out["ok"] is False
    assert out["problem"]


def test_storage_size_returns_nothing_rather_than_guessing():
    from shani_cassini import system_status as ss
    assert ss._storage_size("") == {}
    assert ss._storage_size("not a size at all") == {"used": "not a size at all"}
    # A shape we do not recognise must not produce a fabricated number.
    assert "uncompressed" not in ss._storage_size("12.00GiB")


def test_a_bounded_tool_is_stopped_instead_of_waiting_for_ever(tmp_path, monkeypatch):
    """`lxc` is the LXD client: it answers over lxd.socket, and when that socket
    is silent the command does not fail, it waits. Measured in a real ShaniOS
    slot - unbounded it ran past seven minutes, under `timeout 20` it exits 124.
    Gio.Subprocess reports nothing until the child exits, so a page waiting on
    it with no bound is pending for ever with no way back, and Refresh cannot
    help because the refresh is what is stuck. The bound lives in the runner so
    no page can forget it and no page needs a GLib timer it is not allowed."""
    from shani_cassini import system_status as ss

    fake = tmp_path / "lxc"
    # Builtins only: PATH is this tmp_path alone, so a `sleep` would be
    # "not found" and the fake would exit at once - the test would then pass
    # without the bound ever firing.
    fake.write_text("#!/bin/sh\nwhile :; do :; done\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ss, "STREAM_BOUNDS", {"lxc": 1})

    lines: list = []
    exits: list = []
    ctx = GLib.MainContext.default()
    started = time.monotonic()
    ss.run_stream_tool(["lxc", "list"], lines.append, exits.append)
    while not exits and time.monotonic() - started < 15:
        ctx.iteration(True)

    assert exits, "the read never settled - this is the hang the bound exists for"
    assert time.monotonic() - started < 20, "the bound did not stop the child"
    assert any("stopped" in line for line in lines), \
        f"a stopped read must say so rather than look like an empty result: {lines}"


def test_a_bounded_tool_that_answers_in_time_leaves_no_timer_behind(tmp_path, monkeypatch):
    """The other half of the watchdog: cleanup on the normal exit, not only on
    the timeout.

    The existing bound test only exercises expiry. This covers the case where a
    bounded tool answers *before* its bound, which is the common one, and where
    the watchdog must already be gone. If the timer were left armed, it would
    fire later against a finished read and append "did not answer within Ns and
    was stopped" to a page that already has its answer -- a page contradicting
    itself, from a tool that worked. So this waits past the bound and asserts
    nothing was added and on_exit fired exactly once.
    """
    from shani_cassini import system_status as ss

    fake = tmp_path / "lxc"
    fake.write_text("#!/bin/sh\necho 'pci-0000:00:1f.2 (virtio): /dev/sda'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ss, "STREAM_BOUNDS", {"lxc": 1})

    lines: list = []
    exits: list = []
    ctx = GLib.MainContext.default()
    started = time.monotonic()
    ss.run_stream_tool(["lxc", "list"], lines.append, exits.append)
    while not exits and time.monotonic() - started < 10:
        ctx.iteration(True)
    assert exits, "a tool that answers must settle"
    assert "pci-0000" in "".join(lines), lines

    # Now outlive the bound. A surviving watchdog would fire in here.
    # Non-blocking iteration on purpose: ctx.iteration(True) is a BLOCKING wait,
    # and in this loop there is nothing left to arrive, so it would never
    # return. The suite masked that - with other tests leaving events pending,
    # the blocking form returns by accident, so this test passed in a full run
    # and hung when run alone.
    while time.monotonic() - started < 3.5:
        ctx.iteration(False)
        time.sleep(0.01)

    assert len(exits) == 1, f"on_exit fired {len(exits)} times: {exits}"
    assert not any("stopped" in line for line in lines), \
        f"the watchdog outlived the read and contradicted it: {lines}"
    assert not any("did not answer" in line for line in lines), lines


def test_an_unbounded_tool_is_left_alone(tmp_path, monkeypatch):
    """Only a tool measured to hang gets a bound, so the negative case has to be
    able to fail: the fake here blocks on `read` from a stdin that never closes,
    which is shell-builtins-only and cannot exit early. With an empty table the
    read must still be running after several bound-lengths - if a bound were
    wrongly applied to every tool it would have been stopped and settled. The
    earlier version of this test used a fake that exited in milliseconds, so
    bounding everything would still have passed it."""
    from shani_cassini import system_status as ss

    fake = tmp_path / "virsh"
    fake.write_text("#!/bin/sh\nwhile :; do :; done\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ss, "STREAM_BOUNDS", {})

    lines: list = []
    exits: list = []
    ctx = GLib.MainContext.default()
    started = time.monotonic()
    # The handle is kept and cancelled below. Discarding it is what made this
    # test hang when run on its own: the fake busy-loops for ever, nothing had
    # the means to stop it, and pytest never got to exit. In a full run other
    # tests leave enough pending on the main context to carry the process past
    # it, which is why the suite was green and this test alone was not.
    proc = ss.run_stream_tool(["virsh", "list"], lines.append, exits.append)
    try:
        while not exits and time.monotonic() - started < 4:
            ctx.iteration(False)
            time.sleep(0.01)

        assert exits == [], "an unbounded tool was stopped; only measured tools get a bound"
        assert not any("stopped" in line for line in lines), lines
    finally:
        if proc is not None:
            proc.force_exit()


# --- B2: the LUKS header fields gen-efi started reporting --------------------
#
# gen-efi grew luks_version, luks_cipher, luks_kdf and luks_keyslots_in_use so
# this page would stop asserting "LUKS2" from what LUKS2 usually is. They were
# backend-only until these tests: a field nothing renders is a field nobody has.

def _luks_tab(monkeypatch):
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: True)
    monkeypatch.setattr(encryption.ss, "tpm2_present", _tpm_present(True))
    return encryption, encryption.EncryptionTab()


def test_the_luks_fields_the_tool_reported_are_shown(monkeypatch):
    encryption, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True,
                    "luks_version": "2", "luks_cipher": "aes-xts-plain64",
                    "luks_kdf": "argon2id", "luks_keyslots_in_use": [0, 1]}, None)
    assert tab._luks_rows["luks_version"].get_subtitle() == "2"
    assert tab._luks_rows["luks_cipher"].get_subtitle() == "aes-xts-plain64"
    assert tab._luks_rows["luks_kdf"].get_subtitle() == "argon2id"
    assert tab._luks_rows["luks_keyslots_in_use"].get_subtitle() == "0, 1"


def test_a_luks_field_the_tool_did_not_report_is_not_available(monkeypatch):
    """The page's whole job on this row group is to not guess. An older gen-efi
    reports none of these, and a missing key has to read as unknown rather than
    as an empty cipher or a version of 0."""
    encryption, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True}, None)
    for key, _title in encryption.LUKS_DETAILS:
        assert tab._luks_rows[key].get_subtitle() == encryption.NOT_AVAILABLE, key


def test_an_empty_keyslot_list_is_not_zero_keyslots_in_use(monkeypatch):
    """[] is what a tool says when it reported nothing, not a measurement of
    zero. Rendering it as "0" would be a claim about the keyslots protecting
    the disk, from an empty field."""
    encryption, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True,
                    "luks_version": "", "luks_cipher": None,
                    "luks_kdf": "argon2id", "luks_keyslots_in_use": []}, None)
    assert tab._luks_rows["luks_version"].get_subtitle() == encryption.NOT_AVAILABLE
    assert tab._luks_rows["luks_cipher"].get_subtitle() == encryption.NOT_AVAILABLE
    assert tab._luks_rows["luks_kdf"].get_subtitle() == "argon2id"
    assert tab._luks_rows["luks_keyslots_in_use"].get_subtitle() == \
        encryption.NOT_AVAILABLE


def test_the_luks_rows_are_not_built_on_an_unencrypted_disk(monkeypatch):
    """No encrypted disk, no LUKS header to report, so the group must not be
    there implying one exists."""
    from shani_cassini.tabs import encryption
    monkeypatch.setattr(encryption, "_encrypted", lambda: False)
    tab = encryption.EncryptionTab()
    assert tab._luks_rows == {}


# --- the REAL backend contract, captured from a genuinely encrypted slot -----
#
# Every LUKS test above feeds a hand-written dict. This one feeds the verbatim
# output of `gen-efi tpm2-status --json` from a real booted slot whose root was
# a real LUKS2 volume, captured 2026-09-27. A hand-written dict can agree with
# the page and still disagree with the tool; this cannot, because it IS the
# tool's output. It is the join the other tests could not make: real backend
# bytes in, real widget text out.
#
# The values are also load-bearing as a class of value, not just these strings:
# luks_keyslots_in_use is the JSON number 1 here, where every "not reported"
# case is null. If the page ever rendered 1 as anything but "1", this fails.

ENCRYPTED_SLOT_STATUS = json.loads(
    (Path(__file__).parent / "fixtures" / "tpm2-status-encrypted-slot.json")
    .read_text())


def test_a_real_encrypted_slot_populates_every_luks_row(monkeypatch):
    encryption, tab = _luks_tab(monkeypatch)
    tab._on_status(ENCRYPTED_SLOT_STATUS, None)
    assert tab._luks_rows["luks_version"].get_subtitle() == "2"
    assert tab._luks_rows["luks_cipher"].get_subtitle() == "aes-xts-plain64"
    assert tab._luks_rows["luks_kdf"].get_subtitle() == "argon2id"
    assert tab._luks_rows["luks_keyslots_in_use"].get_subtitle() == "1"


def test_the_real_slot_status_is_actually_encrypted(monkeypatch):
    """Guards the fixture itself. If this ever stops being an encrypted report,
    every test above it is quietly testing the wrong branch - which is exactly
    what happened to the LUKS1 dump fixture that was LUKS2-shaped fiction."""
    assert ENCRYPTED_SLOT_STATUS["encrypted"] is True
    assert ENCRYPTED_SLOT_STATUS["luks_device"]
    assert ENCRYPTED_SLOT_STATUS["luks_keyslots_in_use"] == 1


def test_the_real_slot_cipher_is_not_replaced_by_a_default(monkeypatch):
    """aes-xts-plain64 is what this image's header actually says. A page that
    answered "aes-xts-plain64" because it is the usual answer would also pass
    the string test above, so the fixture is checked against the device's own
    reported value rather than against a constant chosen by the test."""
    assert ENCRYPTED_SLOT_STATUS["luks_cipher"] in ENCRYPTED_SLOT_STATUS.values()
    assert ENCRYPTED_SLOT_STATUS["luks_cipher"] != "aes"


# --- systemd's PCR separator: the re-enrolment advisory --------------------
#
# systemd 261 measures a separator into PCRs 0-7, 9 and 12-14, and Arch's
# mkinitcpio 42-1 started shipping that unit in the initrd. A seal bound to one
# of them can stop opening the disk. Nothing read-only can say whether it has --
# there is no enrolment date, no --list and no dry-run -- so what is tested here
# is that the page warns exactly on the configuration the change affects, and
# says nothing anywhere else.

def _separator(tmp_path, monkeypatch, present):
    """Aim the unit-file probe at a tmp_path the test controls, for real.

    Not a stub: this reads an actual file through the actual os.path.exists, so
    a control that moves the constant still exercises the same code a real
    systemd 261 would.
    """
    from shani_cassini import system_status as ss
    unit = tmp_path / "systemd-pcrosseparator.service"
    if present:
        unit.write_text("[Unit]\nDescription=stub of the real unit\n")
    else:
        # A leftover file from an earlier call would make present=False read as
        # present, which is how the first version of the probe test passed its
        # own first half and failed its second.
        unit.unlink(missing_ok=True)
    monkeypatch.setattr(ss, "PCR_SEPARATOR_UNIT", str(unit))


def test_the_separator_probe_answers_from_the_unit_file(tmp_path, monkeypatch):
    from shani_cassini import system_status as ss
    _separator(tmp_path, monkeypatch, present=True)
    assert ss.pcr_separator_measured() is True
    _separator(tmp_path, monkeypatch, present=False)
    assert ss.pcr_separator_measured() is False


def test_the_separator_pcrs_are_the_ones_systemd_measures():
    """0 and 7 are in the set and 8 is not. This is systemd's documented list
    (0-7, 9, 12-14), and PCR 8 is the boundary that a reader who extrapolated
    "0-15" or "0-9" would get wrong in the other direction."""
    from shani_cassini import system_status as ss
    assert {0, 7} <= ss.SEPARATOR_PCRS
    assert 8 not in ss.SEPARATOR_PCRS
    assert 10 not in ss.SEPARATOR_PCRS and 11 not in ss.SEPARATOR_PCRS
    assert {9, 12, 13, 14} <= ss.SEPARATOR_PCRS


def test_the_bound_pcrs_are_gen_efis_own_rule():
    """gen-efi pins 0+7 with Secure Boot on and 0 with it off. Both land inside
    the changed set, which is why this advisory exists at all -- asserted here
    so that a future edit to either constant breaks a test rather than quietly
    stopping the warning."""
    from shani_cassini import system_status as ss
    assert ss.shani_tpm2_pcr_policy(True) == frozenset({0, 7})
    assert ss.shani_tpm2_pcr_policy(False) == frozenset({0})


def test_an_enrolled_key_bound_to_a_changed_pcr_is_warned_about(tmp_path, monkeypatch):
    _separator(tmp_path, monkeypatch, present=True)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True}, None)
    assert tab._seal_row.get_visible() is True
    assert "0, 7" in tab._seal_row.get_subtitle()
    assert "set automatic unlock up again" in tab._seal_row.get_subtitle()


def test_with_secure_boot_off_only_pcr_0_is_named(tmp_path, monkeypatch):
    _separator(tmp_path, monkeypatch, present=True)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": False}, None)
    assert tab._seal_row.get_visible() is True
    assert "PCR 0," in tab._seal_row.get_subtitle()


def test_a_disk_with_no_tpm2_key_is_never_warned_about(tmp_path, monkeypatch):
    """No key means no seal to go stale. The separator being present is not by
    itself a reason to say anything."""
    _separator(tmp_path, monkeypatch, present=True)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": False, "secure_boot": True}, None)
    assert tab._seal_row.get_visible() is False


def test_a_system_too_old_for_the_separator_is_never_warned_about(tmp_path, monkeypatch):
    _separator(tmp_path, monkeypatch, present=False)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True}, None)
    assert tab._seal_row.get_visible() is False


def test_the_warning_needs_no_pcr_field_from_the_tool(tmp_path, monkeypatch):
    """The whole point of deriving the policy from gen-efi's rule instead of
    reading the LUKS2 token: gen-efi reports no PCR field at all, and a token's
    tpm2-pcrs is a bitmask behind a tab where the enrolling flag used '+'. So the
    status carrying nothing PCR-shaped must still produce the warning -- if this
    ever needed a PCR field to fire, it would be reading a field the tool does
    not send, and would be silent on the machines it exists to help."""
    _separator(tmp_path, monkeypatch, present=True)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status({"tpm2_enrolled": True, "secure_boot": True}, None)
    assert tab._seal_row.get_visible() is True


def test_the_advisory_only_appears_for_a_status_that_carries_a_reason(monkeypatch):
    """Both halves of the row's visibility, because only asserting the first
    makes the second untested: hidden before anything is checked, and still
    hidden after a status that reports no risk. A row that appeared on every
    machine would be a warning nobody reads, and one showing an empty subtitle
    would be inventing data -- the two failures are opposite and both wrong."""
    _enc, tab = _luks_tab(monkeypatch)
    assert tab._seal_row.get_visible() is False
    tab._on_status({"tpm2_enrolled": False, "secure_boot": True}, None)
    assert tab._seal_row.get_visible() is False
    assert tab._seal_row.get_subtitle() == ""


def test_the_captured_slot_is_not_tpm2_enrolled():
    """Guards the fixture, and it is a guard because of what it invalidates.

    tests/fixtures/tpm2-status-encrypted-slot.json is a real capture from a
    genuinely encrypted LUKS2 slot, but that slot unlocks on a passphrase:
    tpm2_enrolled false, tpm2_slots 0, secure_boot false. A first attempt at
    the advisory tests above used it as a TPM2 report and the "no warning here"
    test passed for the wrong reason -- it was silent because there was no key,
    not because this host has no separator. If this capture is ever replaced
    with an enrolled one, these tests need re-reading rather than re-running.
    """
    assert ENCRYPTED_SLOT_STATUS["tpm2_enrolled"] is False
    assert ENCRYPTED_SLOT_STATUS["tpm2_slots"] == 0


def test_a_real_encrypted_slot_with_no_key_never_warns_even_with_the_separator(
        tmp_path, monkeypatch):
    """An encrypted disk with no TPM2 key has no seal that can go stale, so the
    separator has nothing to say about it. Real captured bytes, on the one
    condition that would otherwise produce a warning."""
    _separator(tmp_path, monkeypatch, present=True)
    _enc, tab = _luks_tab(monkeypatch)
    tab._on_status(ENCRYPTED_SLOT_STATUS, None)
    assert tab._seal_row.get_visible() is False


def test_the_separator_is_the_only_thing_that_flips_the_advisory(tmp_path, monkeypatch):
    """One status, the probe toggled and nothing else changed, so silence and
    the warning are attributable to the separator alone. The per-condition tests
    above each hold the other inputs still; this one shows the pair is a single
    switch, which is what makes the proxy in pcr_separator_measured defensible."""
    status = {"tpm2_enrolled": True, "secure_boot": True, "tpm2_slots": 1}
    _separator(tmp_path, monkeypatch, present=False)
    _enc, before = _luks_tab(monkeypatch)
    before._on_status(status, None)
    assert before._seal_row.get_visible() is False
    _separator(tmp_path, monkeypatch, present=True)
    _enc, after = _luks_tab(monkeypatch)
    after._on_status(status, None)
    assert after._seal_row.get_visible() is True


def _fake_hwmon(tmp_path, monkeypatch, chips):
    """Build a hwmon tree a test controls. chips maps dir name to (name, files)."""
    from shani_cassini import system_status as ss
    root = tmp_path / "hwmon"
    root.mkdir(parents=True, exist_ok=True)
    for chip, (name, files) in chips.items():
        base = root / chip
        base.mkdir(parents=True, exist_ok=True)
        (base / "name").write_text(name)
        for filename, body in files.items():
            (base / filename).write_text(body)
    monkeypatch.setattr(ss, "HWMON_ROOT", str(root))
    return root


def test_the_sensor_rows_are_built_from_the_hwmon_tree(tmp_path, monkeypatch):
    """Each row is a reading the fake tree holds, with its own label.

    Shapes are taken from a real machine: coretemp labels its inputs,
    thinkpad labels a temperature and a fan, and the acpi chip holds no
    temp/fan inputs at all and must contribute nothing rather than a blank row.
    """
    from shani_cassini import system_status as ss
    _fake_hwmon(tmp_path, monkeypatch, {
        "hwmon0": ("coretemp", {"temp1_input": "45000", "temp1_label": "Package id 0",
                                "temp2_input": "41000", "temp2_label": "Core 0"}),
        "hwmon1": ("thinkpad", {"temp1_input": "58000", "temp1_label": "CPU",
                                "fan1_input": "3300"}),
        "hwmon2": ("acpi", {}),
    })
    rows = []
    ss.sensors_card(rows.extend)
    assert rows == [("coretemp Package id 0", "45°C"),
                    ("coretemp Core 0", "41°C"),
                    ("thinkpad CPU", "58°C"),
                    ("thinkpad Fan 1", "3300 RPM")]


def test_an_unpopulated_sensor_is_not_shown_as_a_reading(tmp_path, monkeypatch):
    """0, empty and negative inputs are dropped, not rendered.

    All three appear in one real machine's thinkpad driver: temp4..temp7 are
    wired to a permanent 0 because no sensor sits behind them, temp8_input is
    an empty file, and the kernel reports an unavailable sensor as a large
    negative. Rendering any of them would put "0°C" on the page as though it
    were a measurement.
    """
    from shani_cassini import system_status as ss
    _fake_hwmon(tmp_path, monkeypatch, {
        "hwmon0": ("thinkpad", {"temp1_input": "84000", "temp1_label": "CPU",
                                "temp2_input": "0", "temp2_label": "GPU",
                                "temp3_input": "", "temp4_input": "-128000",
                                "fan1_input": "0"}),
    })
    rows = []
    ss.sensors_card(rows.extend)
    assert rows == [("thinkpad CPU", "84°C")]


def test_a_machine_with_no_hwmon_reports_nothing_rather_than_guessing(
        tmp_path, monkeypatch):
    """The absent tree is an empty list, which is what the page renders as
    "None reported by the kernel" - not a zero reading and not a guess."""
    from shani_cassini import system_status as ss
    monkeypatch.setattr(ss, "HWMON_ROOT", str(tmp_path / "not-there"))
    rows = []
    ss.sensors_card(rows.extend)
    assert rows == []


def test_the_power_drivers_come_from_the_active_block_not_the_last_one():
    """The regression this fixture is shaped for.

    `powerprofilesctl list` marks the active profile with `*` and prints the
    profiles in power-saver, balanced, performance order, so the active block
    is the middle one. A parser that resets its block on every header keeps
    whichever profile came last and answers for a profile that is not in force
    - which is the only one the row must not report.
    """
    from shani_cassini import system_status as ss
    assert ss._parse_power_drivers(PPD_LIST, profile="balanced") == \
        "CpuDriver, PlatformDriver"
    assert ss._parse_power_drivers(PPD_LIST, profile="power-saver") == \
        "CpuDriver, PlatformDriver"
    assert ss._parse_power_drivers(PPD_LIST, profile="nope") == ""


def test_the_degraded_flag_is_not_reported_as_a_driver():
    """`Degraded: no` is a state flag on the same block. Listing it beside
    CpuDriver would name a boolean as though it drove the profile."""
    from shani_cassini import system_status as ss
    drivers = ss._parse_power_drivers(PPD_LIST, profile="performance")
    assert "Degraded" not in drivers
    assert "intel_pstate" not in drivers  # the *values* are not the driver names


def test_the_hardware_card_names_the_active_power_profile_and_its_drivers(
        tmp_path, monkeypatch):
    """The row is answered end to end by the fake daemon, not by this host."""
    from shani_cassini import system_status as ss
    monkeypatch.setenv("PATH", f"{_sysinfo_fakes(tmp_path)}:{os.environ['PATH']}")
    out = {}
    ss.hardware_card(out.update)
    assert spin(lambda: len(out) == 8), out
    assert out["hw-power-profile"] == "balanced (CpuDriver, PlatformDriver)"


def test_a_machine_with_no_power_profiles_daemon_says_so_on_its_own_row(
        tmp_path, monkeypatch):
    """The card still completes at 8 keys with the daemon absent.

    A reader that only called back on success would leave the other seven rows
    waiting forever, so the count is the assertion that matters here as much as
    the text.
    """
    from shani_cassini import system_status as ss
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    out = {}
    ss.hardware_card(out.update)
    assert spin(lambda: len(out) == 8), out
    assert out["hw-power-profile"] == "N/A"


def test_a_profile_with_no_driver_lines_still_names_the_profile(tmp_path, monkeypatch):
    """`list` unparseable must not cost the row the answer `get` did give.

    `get` is the documented read of the profile in force; the drivers are an
    extra. Losing them is a shorter cell, not an empty one.
    """
    from shani_cassini import system_status as ss
    # One f-string, no trailing space: a space before the colon makes the
    # first PATH entry a directory that does not exist, so the lookup falls
    # through to the real /usr/bin/powerprofilesctl and this asserts against
    # the machine instead of the fake.
    monkeypatch.setenv("PATH", f"{_sysinfo_fakes(tmp_path, ppd_list='nothing useful')}"
                       f":{os.environ['PATH']}")
    out = {}
    ss.hardware_card(out.update)
    assert spin(lambda: len(out) == 8), out
    assert out["hw-power-profile"] == "balanced"
