"""The pages against the real CLI contracts, with fake shani-deploy /
shani-health / pkexec on PATH printing what the real ones print."""

import json
import os
import shutil
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


# --- fprintd, over its own D-Bus API --------------------------------------
#
# fprintd is not a CLI Cassini runs, so the fake is the D-Bus API: the same
# calls, on the same names, answered the way the real daemon answers them and
# delivered through GLib.idle_add - a probe that assumed a synchronous
# callback would fail here rather than in the field.

DEVICE_PATH = "/net/reactivated/Fprint/device/0"
FINGER = ("right-index-finger", "Right index", 3, "enroll", "enrolled", "2026-09-26T10:00:00Z")
NO_REPLY = ("GDBus.Error:org.freedesktop.DBus.Error.NoReply: Did not receive a reply")
DAEMON_GONE = ("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: "
               "The name net.reactivated.fprint was not provided by any .service files")


class _Reply:
    """A D-Bus reply already unpacked: a{sv} and a(ssuss) arrive as plain
    Python values, which is what GLib.Variant.unpack() gives."""

    def __init__(self, value):
        self._value = value

    def unpack(self):
        return self._value


class _Message:
    def __init__(self, value):
        self._reply = _Reply(value)

    def get_reply(self):
        return self._reply


class _Failed:
    """What a D-Bus error looks like: get_reply() raises."""

    def get_reply(self):
        raise GLib.Error(NO_REPLY)


class FakeFprintd:
    def __init__(self, devices=(DEVICE_PATH,), props=None, fingers=(FINGER,)):
        self.devices = list(devices)
        self.props = {"DevicePresent": True, "DeviceEnabled": True, "Action": "",
                      "Name": "Goodix capacitive", "Driver": "goodixmoc"} if props is None else props
        self.fingers = list(fingers)
        self.bus_error = ""       # set to fail the bus itself
        self.call_error = ()      # (path, iface, method) that must fail
        self.silent = False       # answer nothing at all: a hung daemon
        self.enroll_reply = (True, "ok")
        self.calls = []

    def system_bus(self, ready):
        GLib.idle_add(ready, None, self.bus_error) if self.bus_error \
            else GLib.idle_add(ready, object(), "")

    def call(self, _conn, path, iface, method, params, got, reply_type="(v)"):
        self.calls.append((path, iface, method, params, reply_type))
        if self.silent:
            return None
        if (path, iface, method) in self.call_error:
            GLib.idle_add(got, _Failed(), None)
            return None
        if method == "GetDevices":
            value = self.devices
        elif method == "GetAll":
            value = [self.props]
        elif method == "ListEnrolledFingers":
            value = self.fingers
        elif method == "Enroll":
            value = [self.enroll_reply]   # (bs) is the reply's single argument
        else:                       # EnrollStart, EnrollStop, Delete: no reply
            value = []
        GLib.idle_add(got, _Message(value), None)
        return None

    def methods(self):
        return [c[2] for c in self.calls]


@pytest.fixture
def fake_fprintd(monkeypatch):
    from shani_cassini import system_status as ss
    fake = FakeFprintd()
    monkeypatch.setattr(ss, "_system_bus", fake.system_bus)
    monkeypatch.setattr(ss, "_dbus_call", fake.call)
    return fake


def test_fprintd_status_reads_the_reader_and_its_fingers(fake_fprintd):
    from shani_cassini import system_status as ss
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert err == ""
    assert status["daemon"] is True and status["device_present"] is True
    assert status["device_name"] == "Goodix capacitive"
    assert status["driver"] == "goodixmoc"
    assert status["path"] == DEVICE_PATH
    assert status["fingers"] == [{"finger": "right-index-finger", "nickname": "Right index",
                                  "uid": 3, "state": "enrolled"}]
    assert fake_fprintd.methods() == ["GetDevices", "GetAll", "ListEnrolledFingers"]
    assert fake_fprintd.calls[1][0] == DEVICE_PATH


def test_fprintd_with_no_reader_attached_is_not_a_failure(fake_fprintd):
    from shani_cassini import system_status as ss
    fake_fprintd.devices = []
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert err == ""
    assert status["daemon"] is True and status["device_present"] is False
    assert status["fingers"] == []
    assert fake_fprintd.methods() == ["GetDevices"]


@pytest.mark.parametrize("broken", ["bus", "call"])
def test_fprintd_never_guesses_a_state_nobody_reported(fake_fprintd, broken):
    """A daemon that is absent, or that fails the call, must be an error and
    not "no fingers": the page has to be able to say "not known"."""
    from shani_cassini import system_status as ss
    if broken == "bus":
        fake_fprintd.bus_error = DAEMON_GONE
    else:
        fake_fprintd.call_error = [(ss.FPRINTD_PATH, ss.FPRINTD_MANAGER, "GetDevices")]
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)))
    assert spin(lambda: got)
    status, err = got[0]
    assert status is None
    assert "did not answer" in err or "Connection refused" in err or err


def test_fprintd_status_times_out_on_a_daemon_that_hangs(fake_fprintd):
    from shani_cassini import system_status as ss
    fake_fprintd.silent = True
    got = []
    ss.fprintd_status(lambda st, err: got.append((st, err)), timeout_s=1)
    assert spin(lambda: got, timeout=5.0)
    status, err = got[0]
    assert status is None
    assert "in time" in err


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


def test_biometrics_degrades_to_a_status_page_without_fprintd(monkeypatch):
    from gi.repository import Adw
    from shani_cassini import notebook, system_status as ss
    monkeypatch.setattr(ss, "have_sbin", lambda cmd: False)
    nb = notebook.ShaniosNotebook()
    page = nb.select("biometrics")
    assert isinstance(page, Adw.StatusPage)
    assert page.get_title() == "fprintd is not installed"
    assert "shani-peripherals" in page.get_description()


def test_finger_labels_are_readable(fake_fprintd):
    from shani_cassini.tabs.biometrics import _finger_label
    assert _finger_label("right-index-finger") == "Right Index Finger"
    assert _finger_label("") == ""


def test_biometrics_page_reports_a_reader_and_its_fingers(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.fingers = [FINGER, ("left-thumb", "Left thumb", 4, "enroll", "enrolled", "x")]
    tab = BiometricsTab()
    assert spin(lambda: tab._row_daemon.get_subtitle() == "Running")
    assert tab._row_device.get_subtitle() == "Goodix capacitive · goodixmoc"
    assert tab._row_fingers.get_subtitle() == "2 enrolled"
    assert tab._btn_enroll.get_sensitive()
    assert tab._fingers_group.get_visible()
    titles = _action_row_titles(tab._fingers_group)
    assert titles == ["Right index", "Left thumb"]
    # fake_bin's shani-deploy says profile=gnome
    assert spin(lambda: tab._row_edition.get_title() == "This edition: gnome")
    assert "Works at the login screen" in tab._row_edition.get_subtitle()


def test_biometrics_escapes_every_string_fprintd_hands_over(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.props["Name"] = "Sync & <hold> \"reader\""
    fake_fprintd.fingers = [("right-index-finger", "Tom & \"Jerry\" <thumb>", 7,
                             "enroll", "enrolled", "x")]
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    # Adw parses the row's markup on set, so get_subtitle() gives back what a
    # person sees: the exact string fprintd sent, with the entities consumed as
    # markup. Unescaped input would either be dropped or swallowed as a tag.
    assert tab._row_device.get_subtitle() == 'Sync & <hold> "reader" \u00b7 goodixmoc'
    assert "&amp;" not in tab._row_device.get_subtitle()
    # get_title() hands back the markup as stored, so this is the escaping
    # itself: the entity form can only be there because _esc() ran.
    assert _action_row_titles(tab._fingers_group) == ['Tom &amp; &quot;Jerry&quot; &lt;thumb&gt;']
    # a Gtk.Label on the same row shows the person the original text
    assert "&amp;" not in " ".join(_finger_row_texts(tab._fingers_group)) 


def test_biometrics_says_not_known_when_the_daemon_is_gone(fake_bin, fake_fprintd, monkeypatch):
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    monkeypatch.setattr(ss, "fprintd_installed", lambda: True)
    fake_fprintd.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: "did not answer" in tab._row_device.get_subtitle())
    assert tab._row_fingers.get_subtitle().startswith("Not known")
    assert "0 enrolled" not in tab._row_fingers.get_subtitle()
    assert not tab._btn_enroll.get_sensitive()
    assert not tab._fingers_group.get_visible()


def test_biometrics_names_the_package_when_fprintd_is_missing(fake_bin, fake_fprintd, monkeypatch):
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    monkeypatch.setattr(ss, "fprintd_installed", lambda: False)
    fake_fprintd.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: "Not installed" in tab._row_daemon.get_subtitle())
    assert "shani-peripherals" in tab._row_daemon.get_subtitle()


def test_biometrics_will_not_enroll_on_a_reader_that_is_not_there(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.devices = []
    tab = BiometricsTab()
    assert spin(lambda: tab._row_device.get_subtitle().startswith("No reader"))
    assert "Not known" in tab._row_fingers.get_subtitle()
    assert not tab._btn_enroll.get_sensitive()
    tab._start_enroll()
    assert "EnrollStart" not in fake_fprintd.methods()
    assert tab._enroll is None


def test_enroll_scans_only_while_fprintd_says_enroll(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["timer"])
    assert "EnrollStart" in fake_fprintd.methods()
    assert tab._btn_cancel.get_visible()
    assert not tab._btn_enroll.get_visible()

    fake_fprintd.props["Action"] = "enroll"
    assert tab._enroll_tick() is True
    assert spin(lambda: "Enroll" in fake_fprintd.methods())
    assert spin(lambda: tab._row_enroll.get_subtitle() == "Scan stored (1) - lift your finger "
                                 "and touch it again")

    fake_fprintd.enroll_reply = (False, "too fast")
    assert tab._enroll_tick() is True
    assert spin(lambda: "Scan not accepted: too fast" == tab._row_enroll.get_subtitle())
    assert tab._enroll["scans"] == 1        # a rejected scan does not count

    fake_fprintd.props["Action"] = ""       # fprintd stored the last scan
    assert tab._enroll_tick() is True
    assert spin(lambda: "EnrollStop" in fake_fprintd.methods())
    assert tab._enroll is None
    assert not tab._btn_cancel.get_visible()


def test_cancelling_enrollment_always_stops_the_reader(fake_bin, fake_fprintd):
    """A reader left mid-enroll stays claimed and unusable, so EnrollStop runs
    on the cancel path too."""
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["timer"])
    tab.cancel_enroll()
    assert spin(lambda: "EnrollStop" in fake_fprintd.methods())
    assert tab._enroll is None
    assert not tab._btn_cancel.get_visible()
    assert not tab._entry_name.get_sensitive() is False
    fake_fprintd.props["Action"] = "enroll"
    assert tab._enroll_tick() is False       # the loop is gone


def test_enrollment_gives_up_after_its_timeout(fake_bin, fake_fprintd, monkeypatch):
    from shani_cassini.tabs import biometrics
    tab = biometrics.BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    monkeypatch.setattr(biometrics, "ENROLL_TIMEOUT_S", 0)
    tab._start_enroll()
    assert spin(lambda: tab._enroll is not None and tab._enroll["timer"])
    assert tab._enroll_tick() is False
    assert spin(lambda: "EnrollStop" in fake_fprintd.methods())
    assert tab._enroll is None


def test_delete_asks_fprintd_for_that_finger_uid(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    tab = BiometricsTab()
    assert spin(lambda: tab._row_fingers.get_subtitle() == "1 enrolled")
    tab._delete(3)
    assert spin(lambda: "Delete" in fake_fprintd.methods())
    call = next(c for c in fake_fprintd.calls if c[2] == "Delete")
    assert call[0] == DEVICE_PATH
    arg = call[3][0]
    assert arg.get_type_string() == "u", "Delete takes a bare uint32, not a (u) tuple"
    assert arg.unpack() == 3                 # the uid from ListEnrolledFingers


def test_delete_without_a_status_deletes_nothing(fake_bin, fake_fprintd):
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.bus_error = DAEMON_GONE
    tab = BiometricsTab()
    assert spin(lambda: tab._row_daemon.get_subtitle() != "Asking it…")
    tab._delete(3)
    assert "Delete" not in fake_fprintd.methods()


def test_enroll_start_failure_still_stops_the_reader(fake_bin, fake_fprintd):
    """A failed EnrollStart is the one path where no reader was claimed - and
    EnrollStop is still called, because a half-started enrollment that is not
    closed leaves the reader unusable by the lock screen."""
    from shani_cassini import system_status as ss
    from shani_cassini.tabs.biometrics import BiometricsTab
    fake_fprintd.call_error = [(DEVICE_PATH, ss.FPRINTD_DEVICE, "EnrollStart")]
    tab = BiometricsTab()
    assert spin(lambda: tab._btn_enroll.get_sensitive())
    tab._start_enroll()
    assert spin(lambda: "EnrollStart" in fake_fprintd.methods())
    assert spin(lambda: "EnrollStop" in fake_fprintd.methods())
    assert tab._enroll is None
    assert not tab._btn_cancel.get_visible()
    assert tab._btn_enroll.get_visible()


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


def _finger_row_texts(group):
    """The rendered labels of a group's rows: what a person actually reads."""
    from gi.repository import Gtk
    out = []

    def walk(w):
        c = w.get_first_child()
        while c is not None:
            if isinstance(c, Gtk.Label):
                out.append(c.get_text())
            walk(c)
            c = c.get_next_sibling()
    walk(group)
    return out
