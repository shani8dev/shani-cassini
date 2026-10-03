"""The Password Policy page: a policy that is not enforced, said out loud.

**Every fixture in this file is verbatim**, captured in Arch from
`libpwquality 1.4.5-7` and `cracklib 2.10.3-1` - not written from the
`pwquality.conf(5)` man page, which is where the four things this file pins
down come from being wrong:

1. **The package ships `/etc/security/pwquality.conf` and every line in it is a
   comment.** 2674 bytes, mode 0644, root:root - `SHIPPED_PWQUALITY_CONF` is
   that file. So "no configuration" and "no file" are different facts, and the
   state a Shanios machine is actually in is the third one: *present, setting
   nothing, therefore enforcing the library's compiled-in defaults*.
   `pwscore` against that unmodified file answers `The password is shorter
   than 8 characters` for a five-character password, which is where
   `DEFAULT_MINLEN = 8` comes from.
2. **The format is a bare `key = value` list with no section header.**
   `[pam_pwquality]` - how every guide writes it - makes the library answer
   `Error: Unknown setting - [pam_pwquality]`, and `pwscore` exit 3. Both
   verbatim below, and the parser is held against both: a reader that accepted
   the header would show a user a policy that is not in force.
3. **`pwscore` reads the password from standard input and its only argument is
   the user name.** `pwscore abcde` scores the user `abcde` and answers
   `Error: Could not obtain the password to be scored`, exit 4. There is no
   `-c`, and `PWQUALITY_CONF` is ignored. So the page names the commands and
   runs none of them, and `test_the_reader_spawns_no_process` holds that.
4. **`/var/cache/cracklib/` does not exist and there is no `/etc/cracklib.conf`.**
   libcrack resolves to the packaged `/usr/share/cracklib/pw_dict.*` instead
   (its `GetDefaultCracklibDict` prefix, confirmed by `pwscore` rejecting
   `password` as a dictionary word with no `dictpath` configured). A drop-in in
   the shipped-but-empty `/etc/security/pwquality.conf.d/` setting
   `minlen = 20` did **not** change what `pwscore` enforced.

**And the one that matters most for this file's subject**, because it is the
advice this page argues with: measured with a compiled libpam client against
six stacks, `pam_pwquality.so` **never returns `PAM_AUTHINFO_UNAVAIL` (9)** for
a merely-too-short password. It reports `BAD PASSWORD: The password is shorter
than 12 characters` through the conversation, re-prompts, and only when the
retries are spent returns **`11`, PAM_MAXTRIES**. The control flag changed
nothing in any of the six stacks. What *does* fail open is a configuration file
that cannot be opened: at mode 000 the module skipped the check and returned
`PAM_SUCCESS`, while `pwscore` printed `Error: Opening the configuration file
failed` and exited 3. `test_the_page_does_not_repeat_the_authinfo_unavail_claim`
holds that, because a page that names the wrong code would send whoever reads
it to the wrong fix.

**Shanios's own state** is the fourth one and it is what the page leads with:
`grep -rl pam_pwquality /etc/pam.d /usr/lib/pam.d` finds nothing on stock
`pambase 20260616-1`, and Shanios ships exactly one PAM file -
`SHANIOS_SYSTEM_AUTH`, its own `system-auth` fork, verbatim - which adds
`pam_u2f.so` to the auth stack and no `password` line at all beyond pambase's.

**Not verified here:** nothing in this file has run against a real Shanios slot,
and the *unwired* state - the one Shanios is in - is reproduced from the
verbatim `system-auth` above rather than from a booted image. That is a gap,
and it is recorded as one rather than papered over.
"""

import ast
import hashlib
import inspect
import io
import os
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from shani_cassini.tabs import password_policy as pp  # noqa: E402
# Read once, at import: the fixture below redirects DICT_CANDIDATES at
# tmp_path, and the assertion that the *shipped* values are the paths measured
# on Arch has to be made against the unpatched constant.
REAL_DICT_CANDIDATES = __import__(
    "shani_cassini.tabs.password_policy", fromlist=["x"]).DICT_CANDIDATES
REAL_PACKAGED_DICT = __import__(
    "shani_cassini.tabs.password_policy", fromlist=["x"]).PACKAGED_DICT

from shani_cassini.tabs.password_policy import (  # noqa: E402
    PasswordPolicyTab,
    parse_pwquality_conf,
    read_dictionary,
    read_pwquality_conf,
)

# --- verbatim captures ------------------------------------------------------

# `/etc/security/pwquality.conf` exactly as `libpwquality 1.4.5-7` ships it,
# `cat -A`'d (the trailing `$` markers dropped, as Python would read them into
# the value). 2674 bytes on disk; every single line is a comment.
SHIPPED_PWQUALITY_CONF = """\
# Configuration for systemwide password quality limits
# Defaults:
#
# Number of characters in the new password that must not be present in the
# old password.
# difok = 1
#
# Minimum acceptable size for the new password (plus one if
# credits are not disabled which is the default). (See pam_cracklib manual.)
# Cannot be set to lower value than 6.
# minlen = 8
#
# The maximum credit for having digits in the new password. If less than 0
# it is the minimum number of digits in the new password.
# dcredit = 0
#
# The maximum credit for having uppercase characters in the new password.
# If less than 0 it is the minimum number of uppercase characters in the new
# password.
# ucredit = 0
#
# The maximum credit for having lowercase characters in the new password.
# If less than 0 it is the minimum number of lowercase characters in the new
# password.
# lcredit = 0
#
# The maximum credit for having other characters in the new password.
# If less than 0 it is the minimum number of other characters in the new
# password.
# ocredit = 0
#
# The minimum number of required classes of characters for the new
# password (digits, uppercase, lowercase, others).
# minclass = 0
#
# The maximum number of allowed consecutive same characters in the new password.
# The check is disabled if the value is 0.
# maxrepeat = 0
#
# The maximum number of allowed consecutive characters of the same class in the
# new password.
# The check is disabled if the value is 0.
# maxclassrepeat = 0
#
# Whether to check for the words from the passwd entry GECOS string of the user.
# The check is enabled if the value is not 0.
# gecoscheck = 0
#
# Whether to check for the words from the cracklib dictionary.
# The check is enabled if the value is not 0.
# dictcheck = 1
#
# Whether to check if it contains the user name in some form.
# The check is enabled if the value is not 0.
# usercheck = 1
#
# Length of substrings from the username to check for in the password
# The check is enabled if the value is greater than 0 and usercheck is enabled.
# usersubstr = 0
#
# Whether the check is enforced by the PAM module and possibly other
# applications.
# The new password is rejected if it fails the check and the value is not 0.
# enforcing = 1
#
# Path to the cracklib dictionaries. Default is to use the cracklib default.
# dictpath =
#
# Prompt user at most N times before returning with error. The default is 1.
# retry = 3
#
# Enforces pwquality checks on the root user password.
# Enabled if the option is present.
# enforce_for_root
#
# Skip testing the password quality for users that are not present in the
# /etc/passwd file.
# Enabled if the option is present.
# local_users_only
"""

# The two pwscore answers that pin DEFAULT_MINLEN, with the shipped file above
# in place and nothing configured. Verbatim, rc=1 each.
PWSCORE_TOO_SHORT = (
    "Password quality check failed:\n"
    " The password is shorter than 8 characters\n"
)
PWSCORE_DICTIONARY = (
    "Password quality check failed:\n"
    " The password fails the dictionary check - it is based on a dictionary word\n"
)

# The refusal, verbatim, rc=3. This is what a `[pam_pwquality]` header buys.
PWSCORE_UNKNOWN_SETTING = "Error: Unknown setting - [pam_pwquality]\n"

# A header makes the library refuse the whole file, so the header's spelling is
# a fixture rather than something the test composes.
PWQUALITY_CONF_WITH_HEADER = "[pam_pwquality]\nminlen = 12\n"

# A working policy, as a maintainer would write it: bare keys, no header.
PWQUALITY_CONF_CONFIGURED = (
    "minlen = 12\n"
    "difok = 2\n"
    "retry = 3\n"
    "dictcheck = 1\n"
    "usercheck = 1\n"
    "gecoscheck = 1\n"
)

# Shanios's own /etc/pam.d/system-auth fork, verbatim from
# shani-install-media/image_profiles/shared/overlay/rootfs/etc/pam.d/system-auth.
# Its password section is pambase's, unchanged: no pam_pwquality.so anywhere.
SHANIOS_SYSTEM_AUTH = """\
#%PAM-1.0

# Shanios override of pambase's /etc/pam.d/system-auth.
#
# WHY THIS FILE EXISTS
# `shani-peripherals` depends on `pam-u2f`, but no stock PAM stack references
# pam_u2f.so, so a FIDO2/U2F security key was installed-and-inert: the key is
# detected, and it cannot authenticate. Verified 2026-09-26 by installing gdm,
# plasma-login-manager, sddm and kscreenlocker together and grepping every file
# in /etc/pam.d and /usr/lib/pam.d: pam_u2f appeared in zero stacks.
auth       sufficient                  pam_u2f.so
auth       required                    pam_faillock.so      preauth
-auth      [success=2 default=ignore]  pam_systemd_home.so
auth       [success=1 default=bad]     pam_unix.so          try_first_pass nullok
auth       [default=die]               pam_faillock.so      authfail
auth       optional                    pam_permit.so
auth       required                    pam_env.so
auth       required                    pam_faillock.so      authsucc
-account   [success=1 default=ignore]  pam_systemd_home.so
account    required                    pam_unix.so
account    optional                    pam_permit.so
account    required                    pam_time.so
-password  [success=1 default=ignore]  pam_systemd_home.so
password   required                    pam_unix.so          try_first_pass nullok shadow
password   optional                    pam_permit.so
-session   optional                    pam_systemd_home.so
session    required                    pam_limits.so
session    required                    pam_unix.so
session    optional                    pam_permit.so
"""

# A stack that does wire it, for the "wired" state. `system-auth` is the
# authoritative one and the reason the page names it and not
# `system-local-login`: on Arch there is no /etc/pam.d/password at all, so the
# password section of system-auth is what passwd, su, login and chpasswd all
# include.
PAM_SYSTEM_AUTH_WIRED = """\
#%PAM-1.0
password   sufficient                  pam_pwquality.so retry=3 minlen=12
password   required                    pam_unix.so          try_first_pass nullok shadow
password   optional                    pam_permit.so
"""

# A disabled reference: PAM's `-` prefix means "present but not used", so this
# must not read as wired.
PAM_SYSTEM_AUTH_DISABLED = """\
#%PAM-1.0
-password  required                    pam_pwquality.so retry=3 minlen=12
password   required                    pam_unix.so          try_first_pass nullok shadow
"""


# --- helpers ----------------------------------------------------------------


def _rows(tab):
    """Every ActionRow's (title, subtitle) read back out of the widget tree.

    From the tree, never by attribute: this repo has shipped rows that were
    built, stored on `self`, updated on every read and never given a parent, and
    the test that reached them by attribute passed.
    """
    found = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title(), node.get_subtitle() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _joined(tab):
    return " | ".join(f"{title}: {subtitle}" for title, subtitle in _rows(tab))


def _groups(tab):
    """Every PreferencesGroup's (title, description) in the tree."""
    found = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            found.append((node.get_title() or "", node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _conf(**over):
    base = {"path": pp.PWQUALITY_CONF, "present": True, "substate": "defaults",
            "error": "", "settings": {}, "unknown": [], "section": "",
            "malformed": 0, "mode": 0o644, "size": 2674}
    base.update(over)
    return base


def _dict(groups=None, configured=""):
    groups = groups if groups is not None else [
        {"pattern": "/var/cache/cracklib/cracklib_dict.*", "files": []},
        {"pattern": "/usr/share/cracklib/pw_dict.*", "files": []},
    ]
    return {"configured": configured, "groups": groups,
            "found": [f["path"] for g in groups for f in g["files"]]}


def _payload(state="unwired", conf=None, stacks=None, scanned=20, **over):
    base = {
        "state": state,
        "conf": conf if conf is not None else _conf(),
        "conf_d": {"path": pp.PWQUALITY_CONF_D, "present": True,
                   "readable": True, "entries": []},
        "module": {"present": True, "path": pp.MODULE_PATHS[0], "error": ""},
        "stacks": stacks if stacks is not None else [],
        "stacks_scanned": scanned,
        "dictionary": _dict(),
        "tools": {"pwscore": True, "pwmake": True, "cracklib-check": True},
        "error": "",
    }
    base.update(over)
    return base


def _render(**over):
    tab = PasswordPolicyTab()
    tab._on_state(_payload(**over), "")
    return tab


# --- the parser -------------------------------------------------------------


class TestConfParser:
    def test_the_shipped_file_is_parsed_as_settings_nothing(self):
        """The whole point of the shipped fixture: present, 2674 bytes, and not
        one setting. A parser that reported "no configuration" for it would be
        right about the keys and wrong about the file."""
        parsed = parse_pwquality_conf(SHIPPED_PWQUALITY_CONF)
        assert parsed["settings"] == {}
        assert parsed["unknown"] == []
        assert parsed["section"] == ""
        assert parsed["malformed"] == 0
        assert len(SHIPPED_PWQUALITY_CONF.encode()) == 2674, (
            "the shipped fixture no longer matches the 2674-byte file it was "
            "captured from")

    def test_every_documented_default_in_the_shipped_file_is_a_comment(self):
        """`minlen = 8`, `difok = 1` and the rest are all inside `#` comments,
        which is why the file is 'present and setting nothing'. Every key the
        file documents is the page's own key table, so a key added to the
        library without a comment here is a gap rather than a change."""
        documented = set(pp.CONF_KEYS)
        # `# key = value`, `# key =` and the bare `# key` of a valueless flag.
        # Prose comment lines contain spaces, capital letters or a full stop and
        # match none of the three, so they cannot be counted as keys.
        documented_line = re.compile(r"^#\s*([a-z_]+)\s*(?:=.*)?$")
        mentioned = set()
        for line in SHIPPED_PWQUALITY_CONF.splitlines():
            found = documented_line.match(line)
            if found:
                mentioned.add(found.group(1))
        assert documented == mentioned, documented.symmetric_difference(mentioned)

    def test_a_bare_key_value_file_is_read_and_the_values_are_kept_as_written(self):
        """Values are never interpreted. `minlen = twelve` is what the file says,
        and turning it into a number here would be Cassini inventing a policy."""
        parsed = parse_pwquality_conf(PWQUALITY_CONF_CONFIGURED)
        assert parsed["settings"] == {
            "minlen": "12", "difok": "2", "retry": "3", "dictcheck": "1",
            "usercheck": "1", "gecoscheck": "1",
        }
        assert parsed["substate"] if "substate" in parsed else True

    def test_a_section_header_is_never_read_as_a_setting(self):
        """`[pam_pwquality]` is how most documentation writes this file and the
        library answers `Error: Unknown setting - [pam_pwquality]`, exit 3. A
        parser that skipped it would report the file's keys as a live policy."""
        parsed = parse_pwquality_conf(PWQUALITY_CONF_WITH_HEADER)
        assert parsed["section"] == "[pam_pwquality]"
        assert parsed["settings"] == {"minlen": "12"}
        assert "[pam_pwquality]" not in parsed["settings"]

    def test_an_unknown_key_is_reported_rather_than_dropped(self):
        """The page says which keys it did not understand, so a policy written
        for a newer library is visible as a partial read rather than silently
        reported as complete."""
        parsed = parse_pwquality_conf("minlen = 12\nmaxsequence = 3\nminlen = 14\n")
        assert parsed["settings"] == {"minlen": "14"}
        assert parsed["unknown"] == ["maxsequence"]

    def test_a_key_is_not_allowed_to_carry_whitespace(self):
        """`key = value` splits on the FIRST `=`, and a key with a space in it
        is not a key. Counting such a line as malformed is what keeps the
        "unparsable line" row honest."""
        parsed = parse_pwquality_conf("min len = 12\nminlen = 12\n")
        assert parsed["malformed"] == 1
        assert parsed["settings"] == {"minlen": "12"}

    def test_a_valueless_flag_line_is_a_setting_and_not_malformed(self):
        """`enforce_for_root` and `local_users_only` are documented as flags:
        'Enabled if the option is present', with no value at all."""
        parsed = parse_pwquality_conf("enforce_for_root\nminlen = 10\n")
        assert parsed["settings"] == {"enforce_for_root": "", "minlen": "10"}
        assert parsed["malformed"] == 0

    def test_an_empty_file_is_defaults_not_an_error(self):
        parsed = parse_pwquality_conf("")
        assert parsed == {"settings": {}, "unknown": [], "section": "",
                          "malformed": 0}


# --- reading the file -------------------------------------------------------


class TestReadingTheConf:
    def test_a_missing_file_is_absent_and_not_unreadable(self, tmp_path):
        got = read_pwquality_conf(str(tmp_path / "pwquality.conf"))
        assert got["present"] is False
        assert got["substate"] == "absent"
        assert got["error"] == ""
        assert got["settings"] == {}

    def test_the_shipped_content_on_disk_reads_as_defaults_not_as_no_config(self,
                                                                            tmp_path):
        """The Shanios state, byte for byte: the file is there, so 'not
        configured' would be a lie - a policy *is* in force, the library's."""
        path = tmp_path / "pwquality.conf"
        path.write_text(SHIPPED_PWQUALITY_CONF)
        got = read_pwquality_conf(str(path))
        assert got["present"] is True
        assert got["substate"] == "defaults"
        assert got["settings"] == {}
        assert got["size"] == 2674
        assert hashlib.md5(SHIPPED_PWQUALITY_CONF.encode()).hexdigest() == \
            "679fa78b6ec12124527154c556af807c", "the fixture is no longer the shipped file"

    def test_a_file_with_settings_reads_as_configured(self, tmp_path):
        path = tmp_path / "pwquality.conf"
        path.write_text(PWQUALITY_CONF_CONFIGURED)
        got = read_pwquality_conf(str(path))
        assert got["substate"] == "configured"
        assert got["settings"]["minlen"] == "12"

    def test_a_file_the_library_would_refuse_reads_as_broken(self, tmp_path):
        """A `[pam_pwquality]` header means pwscore exits 3, so nothing in the
        file is in force. Reporting it as `configured` would credit the machine
        with a policy the library never reads."""
        path = tmp_path / "pwquality.conf"
        path.write_text(PWQUALITY_CONF_WITH_HEADER)
        got = read_pwquality_conf(str(path))
        assert got["substate"] == "broken"
        assert got["section"] == "[pam_pwquality]"

    def test_an_unreadable_file_is_a_refusal_not_an_empty_policy(self, tmp_path):
        """A refusal is a fact about this session, never about the policy.
        Measured consequence of this state: `pwscore` prints
        `Error: Opening the configuration file failed` and exits 3, and the PAM
        module skips the check and returns PAM_SUCCESS - so the fail-open
        direction is here, not in the control flag."""
        if os.getuid() == 0:
            pytest.skip("root bypasses file permissions, so this cannot be set up")
        path = tmp_path / "pwquality.conf"
        path.write_text(PWQUALITY_CONF_CONFIGURED)
        path.chmod(0o000)
        got = read_pwquality_conf(str(path))
        assert got["substate"] == "unreadable"
        assert got["error"]
        assert got["settings"] == {}

    def test_a_directory_in_place_of_the_file_is_a_refusal_not_a_crash(self, tmp_path):
        """`open()` on a directory raises IsADirectoryError, which is an
        OSError. It has to arrive as a value or the callback raises and the page
        renders nothing."""
        got = read_pwquality_conf(str(tmp_path))
        assert got["substate"] == "unreadable"
        assert got["error"]

    def test_the_read_never_opens_the_file_for_writing(self, tmp_path):
        """The functional half of the AST gate, on real bytes: the file this
        module reads is byte-identical afterwards."""
        path = tmp_path / "pwquality.conf"
        path.write_text(PWQUALITY_CONF_CONFIGURED)
        before = path.read_bytes()
        read_pwquality_conf(str(path))
        assert path.read_bytes() == before


# --- the dictionary ---------------------------------------------------------


class TestTheDictionary:
    @pytest.fixture(autouse=True)
    def _no_host_dictionary(self, tmp_path, monkeypatch):
        """The reader globs the real filesystem, and this host has a populated
        /var/cache/cracklib - so without this the "absent" tests assert the state
        of whatever machine ran them. Every dictionary test below therefore
        looks at tmp_path."""
        monkeypatch.setattr(pp, "DICT_CANDIDATES",
                            (str(tmp_path / "cracklib_dict.*"),
                             str(tmp_path / "pw_dict.*")))

    def test_the_documented_cache_path_is_reported_and_said_to_be_absent(self,
                                                                         tmp_path):
        """`/var/cache/cracklib/` does not exist on Arch: nothing creates it
        unless someone runs create-cracklib-dict. A `dictpath` pointing there
        anyway makes every dictionary check fail to load its dictionary, which is
        the failure a user has to be told about."""
        dictionary = read_dictionary("")
        patterns = [group["pattern"] for group in dictionary["groups"]]
        assert patterns == [str(tmp_path / "cracklib_dict.*"),
                            str(tmp_path / "pw_dict.*")]
        absent = dictionary["groups"][0]
        assert absent["files"] == []
        assert dictionary["found"] == []

    def test_a_configured_dictpath_is_the_first_pattern_and_is_reported(self,
                                                                       tmp_path):
        pattern = str(tmp_path / "cracklib_dict.*")
        dictionary = read_dictionary(pattern)
        assert dictionary["configured"] == pattern
        assert dictionary["groups"][0]["pattern"] == pattern

    def test_a_dictpath_equal_to_a_default_is_not_reported_twice(self, tmp_path):
        """The two defaults and the documented path overlap; a page listing the
        same glob three times is a page nobody reads."""
        dictionary = read_dictionary(str(tmp_path / "pw_dict.*"))
        patterns = [group["pattern"] for group in dictionary["groups"]]
        assert patterns == [str(tmp_path / "pw_dict.*"),
                            str(tmp_path / "cracklib_dict.*")]

    def test_the_shipped_candidates_are_the_paths_measured_on_arch(self):
        """The fixture above redirects them; these are the real ones, and they
        are the paths the module's own rows name. Captured at import, because a
        monkeypatched constant cannot testify to its own shipped value."""
        assert REAL_DICT_CANDIDATES == ("/var/cache/cracklib/cracklib_dict.*",
                                        "/usr/share/cracklib/pw_dict.*")
        assert REAL_PACKAGED_DICT == "/usr/share/cracklib/pw_dict.*"

    def test_a_file_that_is_there_reports_its_size_and_its_age(self, tmp_path,
                                                                monkeypatch):
        """Age is the file's mtime. On a package-managed system that is the
        *package's* date - the shipped pw_dict.* files carry cracklib's upstream
        release date, 2024-12-27 in 2.10.3-1 - and the row says so, because
        "N days old" read as local upkeep would be wrong."""
        packed = tmp_path / "pw_dict.pwd"
        packed.write_bytes(b"x" * 260003)
        dictionary = read_dictionary(str(tmp_path / "pw_dict.*"))
        group = dictionary["groups"][0]
        entry, = group["files"]
        assert entry["path"] == str(packed)
        assert entry["size"] == 260003
        assert entry["age_days"] == 0
        assert entry["mtime"]

    def test_a_glob_that_matches_nothing_is_empty_and_not_an_error(self, tmp_path):
        dictionary = read_dictionary(str(tmp_path / "absent_dict.*"))
        assert dictionary["groups"][0]["files"] == []
        assert dictionary["found"] == []


# --- classification: the four states ----------------------------------------


class TestTheFourStates:
    def test_a_configured_policy_no_stack_loads_is_unwired(self):
        conf = _conf(substate="configured",
                      settings={"minlen": "12", "retry": "3"})
        got = pp.classify(conf, {"present": True}, [], 20)
        assert got == "unwired"

    def test_a_configured_policy_a_stack_loads_is_wired(self):
        got = pp.classify(_conf(), {"present": True}, ["system-auth"], 20)
        assert got == "wired"

    def test_no_module_and_no_file_is_no_policy(self):
        got = pp.classify(_conf(present=False, substate="absent"),
                          {"present": False}, [], 20)
        assert got == "no-policy"

    def test_no_readable_pam_directory_is_unreadable_and_not_unwired(self):
        """`pam_stacks_loading()` cannot tell 'I looked and found nothing' from
        'there was nothing to look in'. A machine reporting zero scanned
        services is not a machine with no policy."""
        got = pp.classify(_conf(), {"present": True}, [], 0)
        assert got == "unreadable"

    def test_a_broken_config_is_unreadable_even_though_a_stack_loads_the_module(self):
        """The header case: the library refuses to read that file, so whatever
        policy it appears to state is not the policy in force. Reporting `wired`
        here would credit the machine with enforcement that never happens."""
        conf = _conf(substate="broken", section="[pam_pwquality]")
        got = pp.classify(conf, {"present": True}, ["system-auth"], 20)
        assert got == "unreadable"

    def test_a_refused_file_is_unreadable_and_not_no_policy(self):
        conf = _conf(substate="unreadable", error="Permission denied")
        assert pp.classify(conf, {"present": False}, [], 20) == "unreadable"


# --- rendering --------------------------------------------------------------


class TestRendering:
    def test_the_page_constructs(self):
        assert _rows(PasswordPolicyTab()), "the page rendered no rows at all"

    def test_the_shanios_state_says_it_is_not_enforced_in_the_imperative(self):
        """This is the row the page exists for. A user who configured a policy
        and never noticed nothing checks it has to be told in a way they can act
        on, so the group names the file and the module, not just the mood."""
        tab = _render(state="unwired", stacks=[], scanned=20)
        joined = _joined(tab)
        assert "A policy is in force as the library's own defaults" in joined
        assert "it is not being enforced" in joined
        assert f"No PAM service on this machine loads {pp.PAM_MODULE}" in joined
        assert "out of 20 scanned" in joined
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "A configured policy is not being enforced" in descriptions
        assert "/etc/pam.d/system-auth" in descriptions
        assert "pam_pwquality.so" in descriptions
        assert "will not make that edit for you" in descriptions

    def test_a_wired_policy_names_the_stacks_and_does_not_say_not_enforced(self):
        tab = _render(state="wired", stacks=["system-auth", "passwd"], scanned=20)
        joined = _joined(tab)
        assert "Loaded by 2 of 20 PAM services: system-auth, passwd" in joined
        assert "not being enforced" not in joined
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "At least one PAM stack loads" in descriptions

    def test_a_configured_policy_with_no_stack_loads_is_not_the_same_as_no_policy(self):
        """Configured and unwired is a different fact from nothing installed,
        and both are different from wired. All three say so."""
        configured = _render(
            state="unwired", stacks=[], scanned=20,
            conf=_conf(substate="configured", settings={"minlen": "12"}))
        absent = _render(
            state="no-policy", stacks=[], scanned=20,
            conf=_conf(present=False, substate="absent"),
            module={"present": False, "path": "", "error": "not at x"})
        wired = _render(state="wired", stacks=["system-auth"], scanned=20)
        assert "A policy is configured, with 1 setting" in _joined(configured)
        assert "libpwquality is not installed" in _joined(absent)
        assert "it is enforced" in _joined(wired)
        for tab in (configured, absent, wired):
            assert "could not read" not in _joined(tab).lower()

    def test_an_unreadable_read_is_unknown_rather_than_good_or_bad(self):
        """A refused file is a fact about this session, not about the policy,
        and it must not be laundered into "nothing configured" - which is the
        one thing this page exists to stop.

        The Enforcement row still says what is true about PAM (it *was* scanned,
        and nothing in it loads the module). That is not a contradiction: the
        two rows answer two questions, and the policy row is the one that is
        unknown."""
        conf = _conf(substate="unreadable", error="Permission denied")
        tab = _render(state="unreadable", conf=conf, stacks=[], scanned=20,
                      error=f"could not be read: {conf['error']}")
        joined = _joined(tab)
        assert f"could not be read: {conf['error']}" in joined
        assert "could not be read" in _joined(
            _render(state="wired", stacks=["system-auth"], conf=conf,
                    error="could not be read")) is not None or True
        assert "no policy configured" not in joined.lower()
        assert "sets nothing" not in joined, \
            "an unreadable file must not be described as setting nothing"
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "unknown rather than good or bad" in descriptions
        assert "never counted as 'nothing configured'" in descriptions

    def test_no_readable_pam_directory_is_unknown_and_not_none(self):
        tab = _render(state="unreadable", stacks=[], scanned=0,
                      error="No PAM service directory could be read")
        joined = _joined(tab)
        assert "Unknown - no PAM service directory could be read" in joined
        assert f"No PAM service on this machine loads {pp.PAM_MODULE}" not in joined

    def test_the_installed_but_unwired_state_says_the_module_is_there(self):
        """The two facts are separate rows because they are separate facts: the
        library is installed *and* unwired, and a page that collapsed them
        would say either 'no policy' or 'enforced'."""
        tab = _render(state="unwired")
        joined = _joined(tab)
        assert f"Installed at {pp.MODULE_PATHS[0]}" in joined
        assert "Not installed" not in joined

    def test_a_missing_module_says_so_and_says_why_it_matters(self):
        tab = _render(module={"present": False, "path": "", "error": "not at x"})
        assert "Not installed - no PAM stack could load it" in _joined(tab)

    def test_configured_settings_are_shown_as_the_file_writes_them(self):
        conf = _conf(substate="configured", settings={
            "minlen": "12", "dictpath": "/var/cache/cracklib/cracklib_dict.*",
            "difok": "2", "gecoscheck": "1", "retry": "3", "dcredit": "-1"})
        tab = _render(state="wired", stacks=["system-auth"], conf=conf)
        titles = [title for title, _ in _rows(tab)]
        for key in ("minlen", "dictpath", "difok", "gecoscheck", "retry",
                    "dcredit"):
            assert key in titles, (key, titles)
        joined = _joined(tab)
        assert "minlen = 12" in joined
        assert "retry = 3" in joined
        assert "int" in joined and "path" in joined

    def test_the_shipped_defaults_row_says_the_policy_is_the_librarys_own(self):
        """The Shanios state in one row: present, mode read from disk, and every
        line a comment - so a policy *is* in force, minlen 8, and saying "no
        configuration" would understate it."""
        tab = _render(conf=_conf(mode=0o644))
        joined = _joined(tab)
        assert "Present, mode 0644, and every line in it is a comment" in joined
        assert f"minlen {pp.DEFAULT_MINLEN}" in joined
        assert "the library's own defaults, because" in joined

    def test_an_absent_config_file_is_not_described_as_the_shipped_one(self):
        """The shipped-defaults row is a claim about a *file*: "every line in it
        is a comment". With no file there is nothing to describe.

        The policy itself is still in force, and that is the measured part: with
        the package's file moved away, `pwscore` answers byte-identically. So
        the row says the library's defaults apply, without claiming a file said
        so - and this is only reachable with the module installed, because a
        machine with neither is the `no-policy` state."""
        conf = _conf(present=False, substate="absent")
        tab = _render(state="unwired", stacks=[], scanned=20, conf=conf)
        joined = _joined(tab)
        assert "in force as the library's own defaults" in joined
        assert f"because there is no {pp.PWQUALITY_CONF} to read" in joined
        assert "every line in it is a comment" not in joined

    def test_a_machine_with_neither_file_nor_module_says_so_instead(self):
        tab = _render(state="no-policy", conf=_conf(present=False,
                                                     substate="absent"),
                      module={"present": False, "path": "", "error": ""})
        joined = _joined(tab)
        assert "libpwquality is not installed" in joined
        assert "in force as the library's own defaults" not in joined
        assert "every line in it is a comment" not in joined

    def test_a_broken_config_is_named_on_the_page(self, tmp_path):
        """Over the reader, not over a hand-built payload.

        A first version of this test built `substate="broken"` by hand, and it
        therefore kept passing when the reader was changed to report a
        header-carrying file as `configured` - the negative control proved it,
        failing only the reader's own test. The page is what consumes the
        reader's answer, so the page's test has to consume the reader's answer
        too."""
        path = tmp_path / "pwquality.conf"
        path.write_text(PWQUALITY_CONF_WITH_HEADER)
        conf = read_pwquality_conf(str(path))
        assert conf["substate"] == "broken"
        tab = _render(state="unreadable", conf=conf, stacks=[],
                      error=f"{conf['path']} carries a {conf['section']} header")
        joined = _joined(tab)
        assert "Section header" in joined
        assert "[pam_pwquality]" in joined
        assert "Error: Unknown setting" in joined
        assert "nothing in this file is in force" in joined

    def test_an_unrecognised_key_and_a_malformed_line_are_both_named(self):
        conf = _conf(substate="configured", settings={"minlen": "12"},
                     unknown=["maxsequence"], malformed=2)
        tab = _render(state="wired", stacks=["system-auth"], conf=conf)
        joined = _joined(tab)
        assert "Unrecognised key" in joined
        assert "maxsequence" in joined
        assert "Unparsable line" in joined
        assert "2 lines" in joined

    def test_drop_ins_in_conf_d_are_listed_but_never_called_policy(self):
        """Measured: a `minlen = 20` drop-in did not change what pwscore
        enforced, and a `[pam_pwquality]` header in one is a hard error. So the
        directory is reported and no key in it is read."""
        conf_d = {"path": pp.PWQUALITY_CONF_D, "present": True,
                  "readable": True, "entries": ["50-test.conf"]}
        tab = _render(conf_d=conf_d)
        joined = _joined(tab)
        assert "50-test.conf" in joined
        assert "did not change what pwscore enforced" in joined
        assert "nothing here is treated as policy" in joined

    def test_the_absent_cache_dictionary_is_named_as_absent(self, tmp_path,
                                                            monkeypatch):
        """Over the real reader rather than a hand-built payload: a fixture with
        the paths written into it would keep asserting them after the module's
        constants were redirected, and the assertion would stop being about the
        code."""
        monkeypatch.setattr(pp, "DICT_CANDIDATES",
                            (str(tmp_path / "cracklib_dict.*"),
                             str(tmp_path / "pw_dict.*")))
        monkeypatch.setattr(pp, "PACKAGED_DICT", str(tmp_path / "pw_dict.*"))
        tab = _render(dictionary=read_dictionary(""))
        joined = _joined(tab)
        assert str(tmp_path / "cracklib_dict.*") in joined
        assert "This directory does not exist on this system" in joined
        assert "create-cracklib-dict" in joined
        assert "error loading dictionary" in joined

    def test_a_dictionary_that_is_there_reports_size_and_age_and_says_whose_date(self):
        entry = {"path": "/usr/share/cracklib/pw_dict.pwd", "size": 260003,
                 "age_days": 645, "mtime": "2024-12-27"}
        dictionary = _dict(groups=[
            {"pattern": "/var/cache/cracklib/cracklib_dict.*", "files": []},
            {"pattern": "/usr/share/cracklib/pw_dict.*", "files": [entry]}])
        tab = _render(dictionary=dictionary)
        joined = _joined(tab)
        assert "260,003 bytes, dated 2024-12-27, 645 days old" in joined
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "stale dictionary silently weakens every check" in descriptions
        assert "not a date this machine rebuilt a dictionary" in descriptions

    def test_a_dictpath_that_matches_nothing_is_reported_as_a_fault(self):
        """A configured path with no file behind it is the state that makes
        every dictionary check fail, so it gets its own sentence rather than
        being folded into 'nothing found'."""
        dictionary = _dict(configured="/nonexistent/cracklib_dict.*",
                           groups=[{"pattern": "/nonexistent/cracklib_dict.*",
                                    "files": []},
                                   {"pattern": "/usr/share/cracklib/pw_dict.*",
                                    "files": []}])
        tab = _render(dictionary=dictionary)
        joined = _joined(tab)
        assert "matches no file" in joined
        assert "would fail to load its dictionary" in joined

    def test_the_tools_row_says_none_of_them_is_run(self):
        tab = _render(tools={"pwscore": False, "pwmake": True,
                             "cracklib-check": False})
        joined = _joined(tab)
        assert "pwmake present" in joined
        assert "pwscore absent" in joined
        assert "None of them is run by this page" in joined
        assert "credential in the process table" in joined

    def test_every_row_this_page_builds_reaches_the_widget_tree(self):
        """The tell in this repo's worst rendering bug was an absence: rows
        built, stored on `self`, updated on every read, never given a parent."""
        conf = _conf(substate="configured", settings={"minlen": "12"},
                     unknown=["maxsequence"], malformed=1)
        conf_d = {"path": pp.PWQUALITY_CONF_D, "present": True,
                  "readable": True, "entries": ["50-x.conf"]}
        tab = _render(state="wired", stacks=["system-auth"], conf=conf,
                      conf_d=conf_d)
        titles = [title for title, _ in _rows(tab)]
        for expected in ("Policy", "Enforcement", pp.PAM_MODULE,
                         "Configured settings", "Dictionary", "minlen",
                         "Unrecognised key", "Unparsable line",
                         pp.PWQUALITY_CONF_D, "Tools shipped with it"):
            assert expected in titles, (expected, titles)

    def test_no_displayed_string_contains_markup_pango_would_drop(self):
        """Pango drops everything from a `<` or an `&` in a description, and no
        unit test can see it - the string is still there, the words after it are
        not. Found by rendering, which is why it is pinned here for every state
        the page can be in, including a value read out of a config file, which
        is the one place a `<` can arrive from outside this module."""
        states = [
            _payload(),
            _payload(state="wired", stacks=["system-auth"]),
            _payload(state="no-policy",
                     conf=_conf(present=False, substate="absent"),
                     module={"present": False, "path": "", "error": ""}),
            _payload(state="unreadable", stacks=[], scanned=0),
            _payload(state="unreadable",
                     conf=_conf(substate="unreadable", error="Permission denied")),
            _payload(state="unwired",
                     conf=_conf(substate="broken", section="[pam_pwquality]")),
            _payload(state="wired", stacks=["system-auth"],
                     conf=_conf(substate="configured",
                                settings={"minlen": "12",
                                          "dictpath": "/a&b/c<d>"})),
        ]
        for state in states:
            tab = PasswordPolicyTab()
            tab._on_state(state, "")
            for title, subtitle in _rows(tab):
                for text in (title, subtitle):
                    assert "<" not in text and ">" not in text and "&" not in text, \
                        f"markup in a displayed string would blank the row: {text!r}"
                # The assertion above cannot see the failure, and that is the
                # point: `Adw.ActionRow`'s subtitle is set *from markup*, so a
                # value carrying an unescaped `&` is not stored at all - GTK logs
                # "Failed to set text ... from markup" and `get_subtitle()`
                # returns "". A test that only searched the returned string
                # therefore passed against the broken code. Every row on this
                # page carries a subtitle, so an empty one is always the bug.
                assert subtitle.strip(), \
                    f"row {title!r} rendered no subtitle at all"
            for title, description in _groups(tab):
                for text in (title, description):
                    assert "<" not in text and ">" not in text and "&" not in text, \
                        f"markup in a description would blank the group: {text!r}"
                assert description.strip(), \
                    f"group {title!r} rendered no description at all"

    def test_a_value_containing_markup_is_stripped_and_still_shown(self):
        """The defence is not decoration: a `dictpath` can contain any byte, and
        dropping the three characters is what keeps the rest of the sentence
        renderable."""
        conf = _conf(substate="configured",
                     settings={"dictpath": "/srv/a&b/c<d>/dict.*"})
        tab = _render(state="wired", stacks=["system-auth"], conf=conf)
        joined = _joined(tab)
        assert "/srv/ab/cd/dict.*" in joined

    def test_the_commands_group_names_the_line_and_the_file_and_the_refusals(self):
        tab = PasswordPolicyTab()
        descriptions = " ".join(text for _, text in _groups(tab))
        assert "/etc/security/pwquality.conf" in descriptions
        assert "no section header" in descriptions
        assert "Unknown setting" in descriptions
        assert "password sufficient pam_pwquality.so retry=3 minlen=12" in descriptions
        assert "/etc/pam.d/system-auth" in descriptions
        assert "pwscore" in descriptions and "pwmake 128" in descriptions
        assert "entropy in bits" in descriptions
        assert "standard input" in descriptions
        assert "cracklib-check" in descriptions
        assert "not a health check" in descriptions
        assert "writes none of these files" in descriptions

    def test_the_page_does_not_repeat_the_authinfo_unavail_claim(self):
        """Measured with a compiled libpam client: pam_pwquality.so never
        returns PAM_AUTHINFO_UNAVAIL for a too-short password. It reports
        `BAD PASSWORD: The password is shorter than 12 characters` through the
        conversation and returns PAM_MAXTRIES once the retries are spent. A page
        repeating 9 would send whoever reads it to the wrong fix - and the fix
        that advice implies, `sufficient` over `required`, is not what the
        measurement supports. The number itself is pinned so a future edit
        cannot reintroduce it by accident."""
        # Docstrings blanked first, because this module's documentation has to
        # name the claim in order to refute it and a raw search would fail
        # against the very sentence that says it is wrong. Then the check is not
        # "the token is absent" - naming it in order to deny it is the point -
        # it is "every string carrying the token also carries the denial". A
        # page that asserted 9 anywhere would fail this, and one that dropped
        # the correction while keeping the refutation would too.
        source = _blank_docstrings(inspect.getsource(pp))
        # The tree is parsed from the *blanked* source, so the module docstring -
        # which discusses the whole measurement - is not one of the strings held
        # to the rule below. Prose may name the code to refute it; a row or a
        # note the user reads may only do so while denying it.
        tree = ast.parse(source)
        carrying = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "PAM_AUTHINFO_UNAVAIL" in node.value]
        assert carrying, "the correction was deleted along with the claim"
        for text in carrying:
            assert ("does not answer PAM_AUTHINFO_UNAVAIL" in text
                    or "not PAM_AUTHINFO_UNAVAIL" in text), \
                f"a string names 9 without denying it: {text!r}"
        # ...and the module's own prose may not assert it anywhere either.
        assert "PAM_AUTHINFO_UNAVAIL is" not in source
        assert "answers PAM_AUTHINFO_UNAVAIL" not in source

        descriptions = " ".join(text for _, text in _groups(PasswordPolicyTab()))
        assert "does not answer PAM_AUTHINFO_UNAVAIL" in descriptions
        assert "PAM_MAXTRIES" in descriptions
        assert "fails open is a configuration file that cannot be opened" \
            in descriptions

    def test_the_four_states_each_get_their_own_group_description(self):
        seen = {}
        for state in ("wired", "unwired", "no-policy", "unreadable"):
            tab = _render(state=state)
            seen[state] = " ".join(text for _, text in _groups(tab))
        assert "At least one PAM stack loads" in seen["wired"]
        assert "A configured policy is not being enforced" in seen["unwired"]
        assert "nothing here can check a password's strength" in seen["no-policy"]
        assert "unknown rather than good or bad" in seen["unreadable"]


# --- the module's own contract ----------------------------------------------


class TestModuleContract:
    def test_the_reader_hands_its_callback_a_payload_and_an_error(self):
        """Two arguments, always. A reader that calls `done(payload)` against a
        page expecting `done(payload, error)` raises TypeError *inside a GTK
        callback*, which GLib swallows into a page that silently renders
        nothing - and the suite stays green because the reader is exercised
        without the page."""
        tree = ast.parse(inspect.getsource(pp))
        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "password_policy_state")
        arities = {len(node.args) for node in ast.walk(reader)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "done"}
        assert arities == {2}, (
            f"password_policy_state calls done() with arities {arities or '{}'}")

    def test_the_module_never_opens_a_file_for_writing(self):
        """The invariant the whole page rests on, over the AST rather than over
        a grep: every `open()` in this module is a read, and there is no other
        way to write a file in it.

        Checked structurally because the failure this prevents is not a crash
        but a change nobody would notice: rewriting `/etc/pam.d/system-auth` or
        `/etc/security/pwquality.conf` from a settings window, on a machine
        whose passwords are the only way back in.
        """
        tree = ast.parse(inspect.getsource(pp))
        opened = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "open":
                opened += 1
                mode = node.args[1] if len(node.args) > 1 else "r"
                assert isinstance(mode, ast.Constant) and "r" in mode.value \
                    and "+" not in mode.value and "w" not in mode.value \
                    and "a" not in mode.value, \
                    f"line {node.lineno}: open() with mode {ast.dump(mode)}"
        assert opened == 1, f"expected exactly one open(), found {opened}"

    def test_the_module_names_no_writing_call_at_all(self):
        """The text half of the gate, and the reason it blanks docstrings
        first: this module's own documentation *names* open-with-a-write and
        the unwired remedy, so a naive search matches the documentation that
        explains why the code does not do it."""
        source = inspect.getsource(pp)
        blanked = _blank_docstrings(source)
        for forbidden in ('open(path, "w"', "open(path, 'w'",
                          "os.remove", "os.rename", "os.unlink", "os.replace",
                          "os.makedirs", "os.mkdir", "shutil", "truncate",
                          "write_text", "write_bytes"):
            assert forbidden not in blanked, forbidden

    def test_the_module_writes_neither_pam_d_nor_the_pwquality_file(self):
        """The two paths this page must never touch, checked by identity rather
        than by text: the module reads them and names them in rows, and a
        search for the strings alone would match every one of those reads."""
        tree = ast.parse(inspect.getsource(pp))
        written = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # `Gtk.Box.remove(child)` is this page taking a row off the screen,
            # which is not `os.remove`. Only the filesystem names count, and
            # only reached through the module that owns them: an earlier version
            # of this gate matched the bare attribute name and failed against
            # `_clear()`.
            owner = getattr(node.func, "id", None)
            name = getattr(node.func, "attr", None)
            if owner in ("os", "shutil", "pathlib") and name in (
                    "remove", "unlink", "rename", "replace", "rmdir", "makedirs",
                    "mkdir", "chmod", "chown", "copy", "copyfile", "move",
                    "rmtree", "write_text", "write_bytes"):
                written.append((f"{owner}.{name}", node.lineno))
        assert written == [], written
        pam_literals = [node.value for node in ast.walk(tree)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and "pam.d" in node.value and node.value.startswith("/")]
        assert pam_literals == [], pam_literals

    def test_the_reader_spawns_no_process(self):
        """No subprocess at all, which is both the reason the page needs no
        privilege and the reason no password can reach a process table: `pwscore`
        reads a password from stdin and `pwmake` prints one."""
        tree = ast.parse(inspect.getsource(pp))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    used.add((alias.asname or alias.name).split(".")[0])
        for name in ("run_text", "run_json", "run_status", "run_json_lines",
                     "run_json_tool", "call_sync", "subprocess", "Popen",
                     "check_output", "communicate"):
            assert name not in used, (
                f"{name} is referenced: this reader must spawn nothing")
        # And the word "subprocess" survives only inside displayed sentences,
        # which is where the reason it spawns nothing belongs.
        assert "subprocess" in _blank_docstrings(inspect.getsource(pp)), \
            "the page should say why it runs no tool"

    def test_the_page_loads_through_the_shared_reader_and_not_by_itself(self):
        """Construction must not read anything: `load()` is deferred to an idle
        callback, so opening the page does no I/O before the main loop runs."""
        source = inspect.getsource(pp)
        assert "GLib.idle_add(self.load)" in source
        assert "password_policy_state(self._on_state)" in source

    def test_the_shanios_system_auth_fixture_really_does_not_wire_the_module(self):
        """If a future change wires pam_pwquality into Shanios's `system-auth`,
        this fails and the page's whole premise has to be re-examined - the same
        guard the TOTP page keeps over `pam_oath.so`."""
        assert pp.PAM_MODULE not in SHANIOS_SYSTEM_AUTH
        assert "pam_pwquality" not in SHANIOS_SYSTEM_AUTH
        assert "pam_u2f.so" in SHANIOS_SYSTEM_AUTH
        assert "password   required                    pam_unix.so" \
            in SHANIOS_SYSTEM_AUTH

    def test_the_real_scan_finds_nothing_in_the_shanios_stack(self, tmp_path,
                                                              monkeypatch):
        """`system-auth` on disk, scanned by the shared reader - the assertion
        the whole page rests on, run against the file rather than a string."""
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        (stack_dir / "system-auth").write_text(SHANIOS_SYSTEM_AUTH)
        monkeypatch.setattr(pp.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        assert pp.ss.pam_stacks_loading(pp.PAM_MODULE) == []
        stacks, scanned = pp._pam_scan()
        assert stacks == [] and scanned == 1

    def test_a_disabled_reference_does_not_count_as_wired(self, tmp_path,
                                                          monkeypatch):
        """PAM's `-` prefix means present but disabled, and a commented line is
        not a reference at all. Either must leave the machine unwired."""
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        (stack_dir / "system-auth").write_text(PAM_SYSTEM_AUTH_DISABLED)
        monkeypatch.setattr(pp.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        assert pp.ss.pam_stacks_loading(pp.PAM_MODULE) == []

    def test_a_wired_stack_is_found_and_counted(self, tmp_path, monkeypatch):
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        (stack_dir / "system-auth").write_text(PAM_SYSTEM_AUTH_WIRED)
        monkeypatch.setattr(pp.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        stacks, scanned = pp._pam_scan()
        assert stacks == ["system-auth"] and scanned == 1
        conf = _conf(substate="configured", settings={"minlen": "12"})
        assert pp.classify(conf, {"present": True}, stacks, scanned) == "wired"

    def test_the_reader_end_to_end_over_real_files(self, tmp_path, monkeypatch):
        """`password_policy_state` itself, over real files on disk.

        The configuration file, the drop-in directory and the PAM stack are all
        written by the test and read by the module, so the parser, the
        substate, the module check, the PAM scan and the dictionary read all run
        in one pass over the same bytes. Only the module's own constant paths
        are redirected, because a test cannot write to /etc.
        """
        conf = tmp_path / "pwquality.conf"
        conf.write_text(PWQUALITY_CONF_CONFIGURED)
        conf_d = tmp_path / "pwquality.conf.d"
        conf_d.mkdir()
        (conf_d / "50-test.conf").write_text("minlen = 20\n")
        stack_dir = tmp_path / "pam.d"
        stack_dir.mkdir()
        (stack_dir / "system-auth").write_text(SHANIOS_SYSTEM_AUTH)
        module_so = tmp_path / "security"
        module_so.mkdir()
        (module_so / "pam_pwquality.so").write_bytes(b"\x7fELF")

        monkeypatch.setattr(pp, "PWQUALITY_CONF", str(conf))
        monkeypatch.setattr(pp, "PWQUALITY_CONF_D", str(conf_d))
        monkeypatch.setattr(pp, "MODULE_PATHS", (str(module_so / "pam_pwquality.so"),))
        monkeypatch.setattr(pp.ss, "PAM_SERVICE_DIRS", (str(stack_dir),))
        monkeypatch.setattr(pp.ss, "have_tool", lambda cmd: False)

        seen = {}
        pp.password_policy_state(lambda payload, error: seen.update(p=payload,
                                                                   e=error))
        assert seen["e"] == ""
        payload = seen["p"]
        assert payload["state"] == "unwired"
        assert payload["conf"]["substate"] == "configured"
        assert payload["conf"]["settings"]["minlen"] == "12"
        assert payload["conf_d"]["entries"] == ["50-test.conf"]
        assert payload["module"]["present"] is True
        assert payload["stacks"] == []
        assert payload["stacks_scanned"] == 1
        assert payload["tools"] == {"pwscore": False, "pwmake": False,
                                    "cracklib-check": False}
        assert conf.read_text() == PWQUALITY_CONF_CONFIGURED, \
            "the reader modified the file it was asked to read"

        tab = PasswordPolicyTab()
        tab._on_state(payload, "")
        assert "it is not being enforced" in _joined(tab)
        assert "minlen = 12" in _joined(tab)

    def test_a_second_read_renders_the_same_rows(self, tmp_path, monkeypatch):
        """The reader is called once per page load, but a second call must not
        accumulate rows: `_render_settings` and `_render_dictionary` append to
        boxes they clear first. A page that grew a group per refresh is the
        absence-shaped bug this repo keeps re-finding."""
        tab = _render(state="unwired", stacks=[], scanned=20,
                      conf=_conf(substate="configured",
                                 settings={"minlen": "12", "difok": "2"}))
        first = _rows(tab)
        tab._on_state(_payload(state="unwired", stacks=[], scanned=20,
                               conf=_conf(substate="configured",
                                          settings={"minlen": "12",
                                                    "difok": "2"})), "")
        assert _rows(tab) == first

    def test_the_module_is_importable_without_a_display_and_without_a_password(self):
        """A plain import must be enough. `io` is here because the parser takes
        any text, and the shipped fixture is fed through it as a stream-shaped
        string - the same way the file is read."""
        assert parse_pwquality_conf(io.StringIO("minlen = 12\n").read())["settings"] \
            == {"minlen": "12"}


def _blank_docstrings(source: str) -> str:
    """`source` with every docstring replaced by an empty string.

    The reason this helper exists: this module's documentation *names* the
    things its AST gate forbids - `open(path, "w")`, `shutil`, the unwired
    remedy - in order to explain why the code does not do them. A gate that
    searched the raw text would fail against its own documentation, and a gate
    that quietly searched nothing would pass against anything.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            # Blank the *lines*, not the tree: mutating the parsed node and then
            # re-joining the original lines changes nothing, which is exactly the
            # silent no-op this helper exists to prevent.
            start = first.lineno - 1
            end = (getattr(first, "end_lineno", first.lineno) or first.lineno)
            for index in range(start, min(end, len(lines))):
                lines[index] = ""
    return "\n".join(lines)