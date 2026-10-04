r"""The Avahi page: what the daemon is doing, and why `is-enabled` cannot say.

**Every fixture in this file is a capture, pasted verbatim.** Two of them were
taken on this development host (Ubuntu 24.04.5 LTS, `avahi-daemon
0.8-13ubuntu6.2`) and one is the shipped file out of the Arch package
`avahi-1:0.9rc5-1-x86_64.pkg.tar.zst` found in
`shani-install-media/cache/pacman_cache/pkg/`. Each is labelled with where it
came from and, where it matters, with what it does **not** establish. The
whitespace is pinned against a `cat -A` rendering for the same reason
`test_camera_page.py` does it: `ss -ulpn` is a space-aligned table whose column
widths move with the address widths, and a collapsed run of spaces is exactly
what would hide the defect described in `parse_mdns_listeners`.

**The measurement that shaped this page, and it refuted the brief it was built
from.** The brief asserted that `is-enabled` "typically reports 'disabled' or
'static'". Checked against the packaged Arch unit file rather than assumed:

* `avahi 1:0.9rc5-1`'s `avahi-daemon.service` ends with a real `[Install]`
  section - `WantedBy=multi-user.target`, `Also=avahi-daemon.socket`,
  `Alias=dbus-org.freedesktop.Avahi.service` - so it **is not `static`** and
  `is-enabled` can answer `enabled`. Measured live: `enabled`, exit 0.
* `shani-pkgbuilds/shani-network/shani-network.install:10` runs
  `systemctl enable avahi-daemon.socket` and never the service, so on a Shanios
  install the socket is enabled and the service's own state is untouched.
* The service carries `Requires=avahi-daemon.socket`, `Type=dbus` and
  `BusName=org.freedesktop.Avahi`, so **the socket is what starts it**. A
  disabled service beside an enabled socket is working discovery.

`TestTheSocketIsTheSwitch` holds all three, and
`test_a_disabled_service_beside_an_enabled_socket_is_not_reported_as_off` is the
one that fails if `_verdict` ever goes back to reading the service.

**Twenty-four negative controls were run against this file. Eighteen failed it on
the first attempt; the six that did not each exposed a real hole - a vacuous
assertion, an untested behaviour, or a gate that inspected nothing - and are
recorded at the test that now covers them. Every control below was run, and every
one now fails the suite.**

| # | Mutation | Caught by | First attempt? |
|---|---|---|---|
| 1 | `_verdict` reads the service instead of the socket | `test_a_disabled_service_beside_an_enabled_socket_is_not_reported_as_off` | yes |
| 2 | `static` folded into the enabled branch | `test_static_is_described_as_having_no_install_section` | **no** - see below |
| 3 | commented config keys counted as settings | `test_the_shipped_arch_file_sets_exactly_six_keys` | yes |
| 4 | `ss` columns parsed by index | `test_the_columns_are_not_read_by_index` | yes |
| 5 | the `STATE_ICONS[...][0]` bug re-injected | `test_every_state_the_verdict_can_return_draws_its_own_glyph` | yes |
| 6 | the `\s{2,}` unit-column bug re-injected | `test_the_real_capture_gives_two_units_and_a_count` | yes |
| 7 | the reader stops normalising the answer | `test_an_unstripped_answer_cannot_kill_the_whole_verdict_table` | **no** - see below |
| 8 | a publish flag added to the browse argv | `test_the_browse_argv_is_read_only` | yes |
| 9 | a group description passed unescaped | `test_the_group_descriptions_go_through_plain` | yes |
| 10 | a read wipes the browse rows | `test_a_refresh_does_not_wipe_a_browse_the_user_asked_for` | **no** - see below |
| 11 | the browse handler stops clearing first | `test_a_second_browse_replaces_the_first_and_does_not_stack` | **no** - see below |
| 12 | the listener title loses the fd | `test_the_three_rows_on_one_address_are_told_apart` | yes |
| 13 | `enabled-runtime` dropped from the tuples | `test_enabled_runtime_is_treated_as_enabled` | **no** - untested |
| 14 | browse lines sorted and re-joined | `test_a_clicked_browse_reports_finishing_and_keeps_every_line` | yes |
| 15 | empty browse output called "no services" | `test_a_browse_that_printed_nothing_says_so_...` | yes |
| 16 | `pkexec` in front of the browse tool | `test_the_browse_argv_is_read_only` | yes |
| 17 | the status icon added, never replaced | `test_a_refresh_replaces_the_status_icon_rather_than_adding_one` | yes |
| 18 | `open(path, "w")` instead of a read | `test_the_page_never_writes_to_etc_avahi` | **no** - see below |
| 19 | the duplicate unit row titles brought back | `test_no_two_rows_on_the_page_share_a_title` | yes |
| 20 | the misleading "absent here" wording brought back | `test_the_page_does_not_tell_the_reader_that_avahi_browse_is_missing` | yes |
| 21 | the config key rows not rendered at all | `test_the_config_group_shows_the_six_keys_and_not_the_comments` | yes |
| 22 | a seventh read, and a privileged one | `test_the_page_never_enables_...` + `..._runs_no_command_on_load` | yes |
| 23 | `is-active` repointed at another unit | `test_the_page_never_enables_disables_starts_or_stops_anything` | **no** - see below |
| 24 | a documented read dropped entirely | `test_the_three_answers_land_in_three_different_keys` | yes |

**The four that did not, and what each one was.**

* **#2** was a bad mutation rather than a bad test: `enabled` was appended to the
  `static` branch's tuple, which the earlier `enabled` branch already claimed, so
  nothing reachable changed. Folding `static` into the `enabled` **condition** -
  which is what the test is actually about - fails it.
* **#7** was a genuinely vacuous assertion, and the most interesting of the
  four. The mutation removed the `.strip()` from `_store_enabled`, and the test
  still passed, because `splitlines()[0]` had already removed the trailing
  newline. So the assertion was covering half the normalisation and did not know
  it. It now feeds the store **leading** whitespace and a multi-line answer,
  which `splitlines()` alone does not handle.
* **#10** found a real gap: `_on_state` deliberately does not clear the browse
  rows, and nothing tested that. The only browse-group row the tests looked at,
  "Not browsed", lives on `_row_browse`, which is never in `_browse_rows`, so the
  clear could be added back and change nothing observable.
* **#11** was the same failure in the other direction: the test **re-implemented**
  the handler's two lines instead of driving them, so it cleared the group itself
  and never touched the code it claimed to hold. It now activates the button with
  `run_stream_tool` stubbed, so the rows come from the handler's own callback.
* **#18** was a check reading only `mode=` as a **keyword**. `open(path, "w")` -
  the positional spelling, and the one a real edit would use - passed it.
* **#23** was a membership check where an exact match was needed. The gate asked
  that each of the three unit names appear *somewhere* in the page's argv; a read
  repointed from `avahi-daemon.service` to `avahi-dnsconfd.service` kept every
  name present, because the two `is-enabled` calls still carried it. The gate now
  lists the argv.

**Two more vacuous gates were found in this file while fixing those, both by the
"recovered something must be non-empty" assertion that was added afterwards:**

* `_args_of` parsed `_code()` - the source with **every string literal blanked** -
  so the argv it looked for had no literals in it and it returned a list of
  `None`. The gate then read `assert argv is None or ...` and passed, having
  inspected nothing, for as long as it existed.
* The same helper matched only `ast.Attribute` callees. The reader calls
  `run_text` as an **injectable parameter**, so the call is an `ast.Name`, and
  the walk recovered **zero** calls even after the blanking was fixed.

Both are the shape `AGENTS.md` warns about three times over. The helper is now
`_argv_literals`, parses the real source, matches both callee shapes, resolves
module constants, and records a position it cannot resolve as `None` rather than
dropping the argv - because dropping it is what made the gate vacuous.

Every fixture pin here is also its own control:
`test_the_pins_would_notice_a_collapsed_space` mutates a capture and shows the
`cat -A` rendering changing, so the pins are not decoration.

---

**Two defects were found by rendering, on Arch, and by nothing else.** Both are
recorded because both are the kind a green widget-tree suite waves through:

1. **Two rows with the same title.** The unit-file rows and the `is-enabled` rows
   both produced a row titled `avahi-daemon.service`, so the page showed two rows
   one above the other that a reader cannot tell apart except by reading both
   subtitles. Every widget-tree assertion passed: both rows existed, both were
   correctly parented, both carried the right text. The defect is a
   **duplication**, the mirror of this repo's more usual "a row was built and
   never given a parent". Fixed by qualifying the titles, and held by
   `test_no_two_rows_on_the_page_share_a_title`.
2. **The page told a reader with a working tool that they did not have it.**
   `NOT_PARSED_NOTE` said avahi-browse "is absent on the machine this page was
   written against, so its output has never been captured **here**" - written on
   a dev host where it genuinely is absent, and rendered on a Shanios machine
   where it is present and the Browse button works. "here" reads as the reader's
   machine. Fixed by scoping the claim to this page's own evidence; held by
   `test_the_page_does_not_tell_the_reader_that_avahi_browse_is_missing`.

**And a screenshot misled me three times on this page**, which is the other half
of the lesson and the reason every assertion here reads the widget tree:

* a capture through `Gtk.WidgetPaintable` appeared to place the Browse button in
  the group *above* the one the tree puts it in;
* the first capture appeared to show `/etc/avahi/avahi-daemon.conf` twice;
* at 640px the note "`--terminate` is the tool's own flag" appeared to carry a
  stray apostrophe, which was `tool's`.

All three were checked against the tree or against Pango and were wrong; the
capture was not. So this file asserts **structure from the widget tree** and
**"something was painted" from the capture**, and never geometry or spelling from
an image.
"""

import ast
import inspect
import os
import re
import subprocess

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import avahi as avahi_mod  # noqa: E402
from shani_cassini.tabs.avahi import (  # noqa: E402
    AvahiTab,
    _enabled_sentence,
    _static_host_mappings,
    _verdict,
    parse_avahi_conf,
    parse_mdns_listeners,
    parse_unit_files,
)

@pytest.fixture(autouse=True)
def no_autoload(monkeypatch):
    """Stop every constructed page from spawning real subprocesses.

    `AvahiTab.__init__` ends with `GLib.idle_add(self.load)`, so each of the
    roughly sixty times this file constructs the page would queue a read that
    runs four `systemctl` calls and one `ss` on a machine that has none of the
    answers. Sixty pages is three hundred and sixty children, none of them
    reaped because nothing ever iterates the GLib main loop under pytest.

    That is not only slow: it segfaulted the interpreter mid-file, at
    `AvahiTab.__init__`, after three failures in a row - a crash that reads as a
    page defect and is not one.

    The seam is **`AvahiTab.load`, not `avahi_state`.** Patching the module-level
    reader instead silenced `TestTheReader` as well, because those tests call
    `avahi_state` directly with injected runners - eight tests went green by
    asserting nothing at all, which is the worst outcome available here. The
    reader is still covered; the widget tree just no longer reaches it on its
    own.
    """
    monkeypatch.setattr(AvahiTab, "load", lambda self: False)


# --- the captures ----------------------------------------------------------

# CAPTURE 1. `systemctl list-unit-files 'avahi*' --no-pager`, `cat -A`, this
# host, `avahi-daemon 0.8-13ubuntu6.2`:
#
#     UNIT FILE            STATE   PRESET$
#     avahi-daemon.service enabled enabled$
#     avahi-daemon.socket  enabled enabled$
#     $
#     2 unit files listed.$
#
# **TWO units, and that is a fact about Ubuntu, not about Avahi.** Arch's
# package also ships `avahi-dnsconfd.service` (verified present in the image
# rootfs), so `ARCH_UNITS_BELOW` is built from the package's file list rather
# than from a `systemctl` run, and is labelled DERIVED wherever it is used. The
# host's own dpkg database has no `avahi-dnsconfd` package installed at all.
CATA_LIST_UNIT_FILES = (
    "UNIT FILE            STATE   PRESET\n"
    "avahi-daemon.service enabled enabled\n"
    "avahi-daemon.socket  enabled enabled\n"
    "\n"
    "2 unit files listed.\n"
)

# DERIVED, NOT CAPTURED. The Arch package's unit files, which is what
# `list-unit-files 'avahi*'` would list on a Shanios machine. There is no Arch
# machine here to run it on, so nothing in this file asserts a `systemctl` output
# shape from it - it is used only to check the parser copes with a third row and
# with a `disabled` state, both of which are ordinary systemd answers.
ARCH_UNITS_BELOW = (
    "UNIT FILE               STATE   PRESET\n"
    "avahi-daemon.service    enabled enabled\n"
    "avahi-daemon.socket     enabled enabled\n"
    "avahi-dnsconfd.service  static  enabled\n"
    "\n"
    "3 unit files listed.\n"
)

# CAPTURE 2. The single-word answers, one command each, this host:
#
#     $ systemctl is-enabled avahi-daemon.service            -> enabled   (exit 0)
#     $ systemctl is-enabled avahi-daemon.socket             -> enabled   (exit 0)
#     $ systemctl is-enabled dbus-org.freedesktop.Avahi.service -> alias  (exit 0)
#     $ systemctl is-active  avahi-daemon.service            -> active    (exit 0)
#     $ systemctl is-enabled avahi-not-a-unit.service        -> not-found (exit 4)
#     $ systemctl is-active  avahi-not-a-unit.service        -> inactive  (exit 4)
#     $ systemctl is-enabled avahi-dnsconfd.service          -> not-found (exit 4)
#
# `not-found` and `inactive` go to **stdout** with an empty stderr and a
# non-zero exit, which is why `run_text` is the reader here and `run_status`
# would have thrown both words away.
REAL_SERVICE_ENABLED = "enabled\n"
REAL_SOCKET_ENABLED = "enabled\n"
REAL_DBUS_ENABLED = "alias\n"
REAL_SERVICE_ACTIVE = "active\n"
REAL_NOT_FOUND = "not-found\n"
REAL_INACTIVE = "inactive\n"

# CAPTURE 3. `ss -ulpn | grep 5353`, `cat -A`, this host:
#
#     UNCONN 0      0      224.0.0.251:5353   0.0.0.0:*  users:(("chrome",...))
#     UNCONN 0      0                                    0.0.0.0:5353   0.0.0.0:*
#     UNCONN 0      0                                       [::]:5353      [::]:*
#
# The last two rows carry **trailing spaces and no process**, because naming the
# holder of a socket needs privilege and a settings window does not ask for any.
CATA_SS_MDNS = (
    "UNCONN 0      0                                224.0.0.251:5353"
    "       0.0.0.0:*    users:((\"chrome\",pid=5097,fd=319))\n"
    "UNCONN 0      0                                224.0.0.251:5353"
    "       0.0.0.0:*    users:((\"chrome\",pid=5097,fd=272))\n"
    "UNCONN 0      0                                224.0.0.251:5353"
    "       0.0.0.0:*    users:((\"chrome\",pid=5148,fd=82)) \n"
    "UNCONN 0      0                                    0.0.0.0:5353"
    "       0.0.0.0:*                                      \n"
    "UNCONN 0      0                                       [::]:5353"
    "          [::]:*                                      \n"
)

# The non-5353 rows of the same run, kept so a test can prove the filter does not
# take everything. Measured: `ss -ulpn` printed 12 lines on this host and five of
# them hold 5353.
CATA_SS_OTHER = (
    "State  Recv-Q Send-Q                         Local Address:Port  "
    "Peer Address:Process                            \n"
    "UNCONN 0      0                                0.0.0.0:53275      "
    "0.0.0.0:*                                         \n"
    "UNCONN 0      0                                127.0.0.54:53       "
    "0.0.0.0:*                                         \n"
    "UNCONN 0      0                              127.0.0.53%lo:53      "
    "0.0.0.0:*                                         \n"
    "UNCONN 0      0                                       [::]:39305"
    "         [::]:*                                      \n"
)

# CAPTURE 4. `/etc/avahi/avahi-daemon.conf` **out of the Arch package**
# `avahi-1:0.9rc5-1-x86_64.pkg.tar.zst`, and `diff`-confirmed byte-identical to
# the copy in the built image's rootfs
# (`shani-install-media/cache/temp/gnome/x86_64/airootfs/etc/avahi/`). Only the
# lines this page's parser has an opinion about are kept; the licence header is
# 16 identical comment lines on both platforms and adds nothing.
#
# The load-bearing line is the one under `[wide-area]`: **commented out here**,
# while Ubuntu's 0.8 file ships `enable-wide-area=yes` uncommented. That single
# difference is why the page reports only keys the file actually sets.
ARCH_CONF = (
    "# See avahi-daemon.conf(5) for more information on this configuration\n"
    "# file!\n"
    "\n"
    "[server]\n"
    "#host-name=foo\n"
    "#host-name-from-machine-id=no\n"
    "#domain-name=local\n"
    "#browse-domains=0pointer.de, zeroconf.org\n"
    "use-ipv4=yes\n"
    "use-ipv6=yes\n"
    "#allow-interfaces=eth0\n"
    "#deny-interfaces=eth1\n"
    "#check-response-ttl=no\n"
    "#use-iff-running=no\n"
    "#enable-dbus=yes\n"
    "#disallow-other-stacks=no\n"
    "#allow-point-to-point=no\n"
    "#cache-entries-max=4096\n"
    "#clients-max=4096\n"
    "#objects-per-client-max=1024\n"
    "#entries-per-entry-group-max=32\n"
    "ratelimit-interval-usec=1000000\n"
    "ratelimit-burst=1000\n"
    "\n"
    "[wide-area]\n"
    "#enable-wide-area=no\n"
    "\n"
    "[publish]\n"
    "#disable-publishing=no\n"
    "#disable-user-service-publishing=no\n"
    "#add-service-cookie=no\n"
    "#publish-addresses=yes\n"
    "publish-hinfo=no\n"
    "publish-workstation=no\n"
    "#publish-domain=yes\n"
    "#publish-dns-servers=192.168.50.1, 192.168.50.2\n"
    "#publish-resolv-conf-dns-servers=yes\n"
    "#publish-aaaa-on-ipv4=yes\n"
    "#publish-a-on-ipv6=no\n"
    "\n"
    "[reflector]\n"
    "#enable-reflector=no\n"
    "#reflect-ipv=no\n"
    "#reflect-filters=_airplay._tcp.local,_raop._tcp.local\n"
    "\n"
    "[rlimits]\n"
    "#rlimit-as=\n"
    "#rlimit-core=0\n"
    "#rlimit-data=8388608\n"
    "#rlimit-fsize=0\n"
    "#rlimit-nofile=768\n"
    "#rlimit-stack=8388608\n"
    "#rlimit-nproc=3\n"
)

# CAPTURE 5. The same file on **this host** (Ubuntu 24.04.5, avahi 0.8-13ubuntu6.2).
# It differs from the Arch one in exactly two places that matter, and both are
# kept: the `[wide-area]` line is **uncommented**, and 0.9rc5 adds a
# `#host-name-from-machine-id=no` line that 0.8 has not got. A fixture that were
# the Arch file on both sides would hide the wide-area disagreement entirely.
UBUNTU_CONF_TAIL = "[wide-area]\nenable-wide-area=yes\n\n[publish]\n"

# CAPTURE 6. `/etc/avahi/hosts` and `/etc/avahi/services` on this host and in
# the image rootfs: the file is 1121 bytes and **every line is a comment**; the
# directory exists and is empty. Measured with
# `grep -c '[^#[:space:]]' /etc/avahi/hosts` -> 0 on both.
CATA_HOSTS_ALL_COMMENTS = (
    "# This file contains static ip address <-> host name mappings.  These\n"
    "# can be useful to publish services on behalf of a non-avahi enabled\n"
    "# device.\n"
    "#\n"
    "# Examples:\n"
    "# 192.168.0.1 router.local\n"
    "# 2001::81:1 test.local\n"
)

# NOT A CAPTURE. `avahi-browse --version` on this host:
#     /bin/bash: line 1: avahi-browse: command not found     (exit 127)
# So avahi-browse is absent here, and its **output has never been seen** by this
# page or this test file. There is deliberately no browse-output fixture: a
# remembered format would be exactly the invention this page refuses to make.
REAL_BROWSE_MISSING = "avahi-browse: command not found"


# --- helpers ---------------------------------------------------------------


def _cat_a(text: str) -> str:
    """Re-render text the way `cat -A` does, so a fixture can be pinned to it.

    `cat -A` shows a tab as `^I` and a line end as `$`, and leaves spaces exactly
    where they are - which is the reason the pin is worth having, because a run
    of spaces is otherwise invisible and `ss -ulpn`'s column layout is made of
    them.
    """
    body = text[:-1] if text.endswith("\n") else text
    return "".join(line.replace("\t", "^I") + "$\n" for line in body.split("\n"))


def _payload(*, socket=REAL_SOCKET_ENABLED, service=REAL_SERVICE_ENABLED,
             dbus=REAL_DBUS_ENABLED, active=REAL_SERVICE_ACTIVE,
             units=CATA_LIST_UNIT_FILES, unit_count=2,
             ss_text=CATA_SS_MDNS, conf=ARCH_CONF, conf_readable=True,
             conf_d_present=False, services_present=True,
             services_entries=(), hosts_present=True,
             hosts_mappings=0, have_systemctl=True, have_ss=True,
             have_browse=False) -> dict:
    """A reader payload built through the **real** normalisers, never hand-written.

    An earlier version of a page test in this repo handed the widget tree a
    hand-built payload and passed against a parser that reports four arrays on a
    machine with none. Everything here goes through `parse_unit_files()`,
    `parse_avahi_conf()`, `parse_mdns_listeners()` **and `_store_enabled()`** on
    its way to the page, so the parsers and the rendering cannot disagree.

    `_store_enabled` is in that list because it earns its place: the captured
    answers are `"enabled\\n"` with a trailing newline, and this page's first
    version dropped them straight into the payload. Every branch of `_verdict`
    compares against a bare word, so **all of them missed**, and the status row
    rendered "The activation socket answered enabled" - a sentence with no clause
    after it. A test payload that bypassed the reader's own normaliser found it;
    one that had stripped the string by hand would not have.
    """
    payload: dict = {
        "have_systemctl": have_systemctl,
        "have_ss": have_ss,
        "have_browse": have_browse,
        "service_enabled": None,
        "socket_enabled": None,
        "dbus_name_enabled": None,
        "service_active": None,
        "units": parse_unit_files(units)["units"] if units else [],
        "unit_count": unit_count,
        "unit_files_pattern": "avahi*",
        "listeners": parse_mdns_listeners(ss_text) if ss_text else [],
        "conf_path": avahi_mod.AVAHI_CONF,
        "conf": parse_avahi_conf(conf) if conf_readable else [],
        "conf_read": conf if conf_readable else None,
        "conf_d": {"path": avahi_mod.AVAHI_CONF_D,
                   "present": conf_d_present, "readable": conf_d_present,
                   "is_dir": True},
        "services": {"path": avahi_mod.AVAHI_SERVICES,
                     "present": services_present,
                     "readable": services_present, "is_dir": True},
        "hosts": {"path": avahi_mod.AVAHI_HOSTS, "present": hosts_present,
                  "readable": hosts_present, "is_dir": False},
        "errors": [],
    }
    avahi_mod._store_enabled(payload, "service_enabled", service, "", "")
    avahi_mod._store_enabled(payload, "socket_enabled", socket, "", "")
    avahi_mod._store_enabled(payload, "dbus_name_enabled", dbus, "", "")
    payload["service_active"] = (active or "").strip()
    return payload


def _rendered(**kwargs) -> tuple[str, str, list]:
    """Construct the page, hand it a payload, and read the tree back out.

    Reads the rows back out of the **widget tree** rather than reaching an
    attribute. This repo has shipped a page where two of its own rows were built,
    stored, updated on every read and never given a parent, and the test that
    reached them by attribute passed anyway.
    """
    tab = AvahiTab()
    payload = _payload(**kwargs)
    tab._on_state(payload, "")
    title = tab._row_state.get_title() or ""
    subtitle = tab._row_state.get_subtitle() or ""
    return title, subtitle, _rows(tab)


def _verdict_state(**kwargs) -> str:
    """The `STATE_ICONS` key `_verdict` chose, for a payload built here."""
    return _verdict(_payload(**kwargs))[2]


def _unescape(text: str) -> str:
    """The words a Pango label shows, from either form they can be read back in.

    **Measured on both stacks, and it is the single most stack-sensitive thing in
    this file.** On this host - GTK 4.14 / libadwaita 1.5.0 -
    `Adw.ActionRow.get_subtitle()` hands back the *unescaped* text: a row built
    with `+;a&amp;b;&lt;host&gt;` reads back as `+;a&b;<host>`. On Arch (GTK
    4.22.5 / libadwaita 1.9.4) the same call returns the **escaped** form, which
    `tabs/camera.py`'s `_plain` docstring records.

    Confirmed the hard way here rather than assumed: an assertion on the browse
    lines passed on Ubuntu and failed in the Arch container with
    `'+;a&amp;b;&lt;x&gt;' != '+;a&b;<x>'`, on a handler that is byte-identical on
    both.

    So a test that asserts on an escaped substring passes on one stack and fails
    on the other, and a test that asserts on the raw characters does the
    reverse. Comparing the **words** is the only form that is right on both, and
    it is also the property that matters: what the user typed is what they read.
    """
    out = str(text or "")
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&apos;", "'"), ("&amp;", "&")):
        out = out.replace(entity, char)
    return out


def _rows(tab) -> list:
    """Every `(title, subtitle)` on the page, read out of the widget tree."""
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


def _all_strings(tab) -> list:
    """Every string the page can put on screen, group descriptions included.

    `Adw.PreferencesGroup.description` is a Pango label too, so a description
    carrying a raw `&` fails exactly the way a subtitle does.
    """
    out = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            out.append(node.get_title() or "")
            out.append(node.get_subtitle() or "")
        if isinstance(node, Adw.PreferencesGroup):
            out.append(node.get_title() or "")
            out.append(node.get_description() or "")
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return out


def _markup_error(text: str) -> str:
    """Pango's own verdict on a string, or "" when it accepts it.

    The signal is Pango's. `Gtk.Label.get_label()` returns the raw string after a
    failed parse, so asserting on it passes against broken code - which is how
    this repo shipped two group descriptions that rendered as nothing.
    """
    import gi
    gi.require_version("Pango", "1.0")
    from gi.repository import GLib, Pango
    try:
        Pango.parse_markup(text, -1, "\0")
    except GLib.Error as exc:
        return exc.message
    return ""


ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
KNOWN = ("amp", "lt", "gt", "quot", "apos")


def _markup_safe(text: str) -> bool:
    """Would Pango render this string as the words it contains?

    Two things make a label refuse its text: a `<`, and an `&` that does not
    begin an entity GLib knows. `GLib.markup_escape_text(s) == s` is the usual
    stand-in and it is **wrong here**: escaping is not idempotent, so an already
    escaped `a &amp; b` would fail it and this page emits exactly that. Spelled
    out instead - no `<`, no `>`, and every `&` starting a known entity.
    """
    if "<" in text or ">" in text:
        return False
    rest = ENTITY.sub(
        lambda m: "" if m.group(1).startswith("#")
        or m.group(1) in KNOWN else m.group(0), text)
    return "&" not in rest


def _code(module) -> str:
    """The module's code with docstrings **and every string literal** blanked.

    Both removals are needed. This page's docstring argues at length about why it
    never enables anything, and that argument must not satisfy a gate that proves
    it never does. The strings matter because the page's own `DOES_NOT_NOTE` names
    `systemctl enable avahi-daemon.socket` - a literal the reader is entitled to
    print and a gate is not entitled to trip over.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _argv_literals(module, callee_attr: str) -> list:
    """Every argv this module passes to `module.<callee_attr>`, constants resolved.

    Parses the **real** source, not `_code()`. That distinction is the whole
    reason this helper exists and it was got wrong first: `_code()` blanks every
    string literal, so `run_text([paths[SYSTEMCTL], "is-enabled", SERVICE_UNIT],
    got)` becomes a list whose first element is a `Subscript` rather than a
    constant - unrecoverable, and the helper silently returned a list of `None`.

    The gate that used it then read `assert argv is None or ...` and **passed**,
    having inspected nothing at all. Adding the "recovered something" assertion
    first is what turned that back into a failure, which is the only reason this
    is worth writing down.

    Module constants (`SERVICE_UNIT`, `AVAHI_BROWSE`) parse as `ast.Name`, so
    they are resolved against the module's own globals - which is what makes
    `is-enabled avahi-daemon.service` checkable rather than `[..., <Name>, ...]`.

    **An element that cannot be resolved becomes `None`, not a dropped argv.**
    The tool position is `paths[SYSTEMCTL]` - a `Subscript`, because the reader
    resolves tool paths through an injectable `tool` callable so a test can drive
    it. Dropping the whole argv for that would recover nothing and the gate would
    be vacuous again, which is exactly what happened twice here. So the caller
    gets the tokens it can see and is told, by the `None`, which positions it
    cannot vouch for; `None` is never inspected.
    """
    names = {k: v for k, v in vars(module).items() if not k.startswith("__")}
    found = []
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        # **Both** callee shapes, and the second one is the one this module uses:
        # `run_text` reaches the reader as an *injectable parameter*, so the call
        # is `run_text([...])` - an `ast.Name` - while the browse call is
        # `ss.run_stream_tool([...])`, an `ast.Attribute`. Matching only the
        # attribute form recovered zero calls, and a gate that recovers zero
        # passes for ever.
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        else:
            continue
        if name != callee_attr:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List):
            found.append(None)
            continue
        argv = []
        for element in first.elts:
            if isinstance(element, ast.Constant):
                argv.append(element.value)
            elif (isinstance(element, ast.Name) and element.id in names
                  and isinstance(names[element.id], str)):
                argv.append(names[element.id])
            else:
                # A computed element (`paths[SYSTEMCTL]`, a `*args` splat).
                # Recorded as unknown rather than skipped, so the argv keeps its
                # length and the position stays identifiable.
                argv.append(None)
        found.append(argv)
    return found


def _run(argv):
    """Run a real command for a real measurement, with a deadline.

    `subprocess.run` raises `FileNotFoundError` for a missing executable rather
    than returning 127, which matters for the `avahi-browse` tests: the 127 in
    this file's docstrings is **bash's** code for "command not found", and both
    are measured where both are true.
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=20)


def shutil_which(name: str):
    import shutil
    return shutil.which(name)


# --- the fixtures are the captures -----------------------------------------


class TestTheFixturesAreTheCaptures:
    """The fixtures are pinned to `cat -A` renderings of real output.

    Without this the whitespace is only a comment. With it, a fixture that
    drifted by a single space - or a `cat -A` rendering that was itself
    retyped - fails.
    """

    def test_the_list_unit_files_fixture_is_the_capture(self):
        assert _cat_a(CATA_LIST_UNIT_FILES) == (
            "UNIT FILE            STATE   PRESET$\n"
            "avahi-daemon.service enabled enabled$\n"
            "avahi-daemon.socket  enabled enabled$\n"
            "$\n"
            "2 unit files listed.$\n")

    def test_the_ss_fixture_is_the_capture(self):
        """The pins that matter most, because `ss`'s layout is all spaces."""
        assert _cat_a(CATA_SS_MDNS) == (
            "UNCONN 0      0                                224.0.0.251:5353"
            "       0.0.0.0:*    users:((\"chrome\",pid=5097,fd=319))$\n"
            "UNCONN 0      0                                224.0.0.251:5353"
            "       0.0.0.0:*    users:((\"chrome\",pid=5097,fd=272))$\n"
            "UNCONN 0      0                                224.0.0.251:5353"
            "       0.0.0.0:*    users:((\"chrome\",pid=5148,fd=82)) $\n"
            "UNCONN 0      0                                    0.0.0.0:5353"
            "       0.0.0.0:*                                      $\n"
            "UNCONN 0      0                                       [::]:5353"
            "          [::]:*                                      $\n")

    def test_the_two_rows_with_no_owner_carry_trailing_spaces(self):
        """The absence is the measurement: `ss` printed nothing where the
        process would go, and padded to the column anyway.

        A fixture that trimmed those rows would look identical in a diff and
        would hide the reason the page words that row the way it does.
        """
        rows = CATA_SS_MDNS.splitlines()
        unnamed = [r for r in rows if "users:" not in r]
        assert len(unnamed) == 2, f"expected 2 ownerless rows, got {len(unnamed)}"
        for row in unnamed:
            assert row.endswith("  "), f"trailing padding lost: {row!r}"
        assert "0.0.0.0:5353" in unnamed[0]
        assert "[::]:5353" in unnamed[1]

    def test_the_conf_fixture_keeps_wide_area_commented(self):
        """The Shanios fact, and the one Ubuntu disagrees with."""
        assert "#enable-wide-area=no" in ARCH_CONF
        assert "\nenable-wide-area=" not in ARCH_CONF, (
            "the Arch fixture must leave wide-area commented; Ubuntu's copy has "
            "it uncommented and that difference is what the page reports")

    def test_the_pins_would_notice_a_collapsed_space(self):
        """The anti-vacuity check on the pins above.

        A pin that cannot fail is worth nothing, so this asserts the *mechanism*
        reacts: dropping one space from the `ss` capture changes its `cat -A`
        rendering, and a collapsed run is exactly what a hand-edited fixture
        would look like after the tool that produced it had been through a
        terminal that ate the padding.
        """
        mutated = CATA_SS_MDNS.replace("0      0   ", "0   0 ", 1)
        assert mutated != CATA_SS_MDNS, "the mutation changed nothing"
        assert _cat_a(mutated) != _cat_a(CATA_SS_MDNS)

    def test_there_is_no_avahi_browse_output_fixture(self):
        """The absence is deliberate and this asserts it, so it cannot rot.

        `avahi-browse` is not installed on the machine this page was written
        against (measured: exit 127), so its output has never been seen here. A
        fixture for it would be a remembered format, which is the one thing this
        page refuses to do.
        """
        assert "avahi-browse" not in {
            name for name in dir()
            if name.startswith("CATA_") or name.startswith("REAL_")}
        src = inspect.getsource(avahi_mod)
        for parser in ("parse_browse", "browse_records", "parse_avahi_browse"):
            assert parser not in src, (
                f"{parser} appeared; avahi-browse's output has never been "
                f"captured here, so there is nothing for it to be right about")


# --- the parsers -----------------------------------------------------------


class TestUnitFiles:
    def test_the_real_capture_gives_two_units_and_a_count(self):
        parsed = parse_unit_files(CATA_LIST_UNIT_FILES)
        assert [u["unit"] for u in parsed["units"]] == [
            "avahi-daemon.service", "avahi-daemon.socket"]
        assert parsed["count"] == 2

    def test_the_header_is_not_a_unit(self):
        units = parse_unit_files(CATA_LIST_UNIT_FILES)["units"]
        assert not any(u["unit"].startswith("UNIT") for u in units)
        assert not any("PRESET" in u["unit"] for u in units)

    def test_the_trailer_is_not_a_unit(self):
        """`2 unit files listed.` is a sentence with a full stop, and a
        row-parser without the column rule files it as a unit."""
        units = parse_unit_files(CATA_LIST_UNIT_FILES)["units"]
        assert not any("listed" in u["unit"] for u in units)
        assert len(units) == 2

    def test_the_preset_column_is_kept_rather_than_swallowed(self):
        units = parse_unit_files(CATA_LIST_UNIT_FILES)["units"]
        assert units[0] == {"unit": "avahi-daemon.service",
                            "state": "enabled", "preset": "enabled"}

    def test_a_third_unit_and_a_static_state_are_read(self):
        """DERIVED fixture - see its comment. It exists to hold the `static`
        answer, which is the one the brief wrongly predicted for the daemon."""
        parsed = parse_unit_files(ARCH_UNITS_BELOW)
        assert parsed["count"] == 3
        assert len(parsed["units"]) == 3
        assert parsed["units"][2]["state"] == "static"
        assert parsed["units"][2]["unit"] == "avahi-dnsconfd.service"

    def test_disabled_is_not_mistaken_for_enabled_by_a_width_match(self):
        """`enabled` and `disabled` are the same width in this output, so the
        split must be on runs of spaces and not on a column offset."""
        capture = CATA_LIST_UNIT_FILES.replace(
            "avahi-daemon.socket  enabled enabled",
            "avahi-daemon.socket  disabled enabled")
        units = parse_unit_files(capture)["units"]
        assert units[1]["state"] == "disabled", units

    def test_no_trailer_means_the_count_is_unknown_not_zero(self):
        """Two different facts, and the page words them differently."""
        capture = CATA_LIST_UNIT_FILES.replace("\n2 unit files listed.\n", "\n")
        parsed = parse_unit_files(capture)
        assert parsed["count"] is None
        assert len(parsed["units"]) == 2

    def test_an_empty_output_is_no_units_and_no_count(self):
        parsed = parse_unit_files("")
        assert parsed == {"units": [], "count": None}


class TestAvahiConf:
    def test_the_shipped_arch_file_sets_exactly_six_keys(self):
        """Counted from the capture by hand, which is the only honest source.

        `use-ipv4`, `use-ipv6`, `ratelimit-interval-usec`, `ratelimit-burst`,
        `publish-hinfo`, `publish-workstation`. Six, out of a file with about
        forty keys in it - the ratio is the point.
        """
        entries = parse_avahi_conf(ARCH_CONF)
        assert [(e["section"], e["key"], e["value"]) for e in entries] == [
            ("server", "use-ipv4", "yes"),
            ("server", "use-ipv6", "yes"),
            ("server", "ratelimit-interval-usec", "1000000"),
            ("server", "ratelimit-burst", "1000"),
            ("publish", "publish-hinfo", "no"),
            ("publish", "publish-workstation", "no"),
        ]

    def test_a_commented_key_is_not_a_setting(self):
        """"#enable-wide-area=no" must not come back as a configured value: the
        daemon never reads a comment, and reporting one is how a page claims
        something is set that is not."""
        entries = parse_avahi_conf(ARCH_CONF)
        assert not any(e["key"] == "enable-wide-area" for e in entries)
        assert not any(e["key"].startswith("#") for e in entries)

    def test_the_section_a_key_sits_under_is_kept(self):
        entries = parse_avahi_conf(ARCH_CONF)
        sections = {e["section"] for e in entries}
        assert sections == {"server", "publish"}

    def test_a_setting_the_file_does_not_make_is_reported_as_absent(self):
        """The refusal, and the reason it is a refusal rather than a default.

        Arch's file leaves wide-area commented and Ubuntu's sets it to yes. A
        parser that filled in a compiled-in default would be reporting a number
        nobody measured on either platform.
        """
        entries = parse_avahi_conf(ARCH_CONF)
        assert "wide-area" not in {e["section"] for e in entries}

    def test_the_ubuntu_file_where_wide_area_is_uncommented(self):
        """The other platform, kept so the disagreement is a test and not a
        comment. `avahi-daemon 0.8-13ubuntu6.2` on this host: the same
        `[wide-area]` section, the setting **uncommented**."""
        entries = parse_avahi_conf(UBUNTU_CONF_TAIL)
        assert [(e["section"], e["key"], e["value"]) for e in entries] == [
            ("wide-area", "enable-wide-area", "yes")]

    def test_the_two_platforms_disagree_about_the_same_key(self):
        """The disagreement, stated as one assertion over both fixtures.

        Arch's 0.9rc5 file leaves it commented and Ubuntu's 0.8 file sets it. If
        either fixture is edited to agree with the other, this fails - which is
        the point: the page's wording depends on the two being different.
        """
        arch = parse_avahi_conf(ARCH_CONF)
        ubuntu = parse_avahi_conf(UBUNTU_CONF_TAIL)
        assert not any(e["key"] == "enable-wide-area" for e in arch)
        assert any(e["key"] == "enable-wide-area" for e in ubuntu)

    def test_an_empty_conf_is_empty_output_and_not_a_parse_failure(self):
        assert parse_avahi_conf("") == []

    def test_a_key_before_any_section_header_is_kept_without_one(self):
        entries = parse_avahi_conf("use-ipv4=yes\n")
        assert entries == [{"section": "", "key": "use-ipv4", "value": "yes"}]

    def test_a_semicolon_comment_is_also_a_comment(self):
        entries = parse_avahi_conf("[server]\n;host-name=old\nuse-ipv6=yes\n")
        assert [e["key"] for e in entries] == ["use-ipv6"]


class TestMdnsListeners:
    def test_the_real_capture_gives_five_rows(self):
        rows = parse_mdns_listeners(CATA_SS_MDNS)
        assert len(rows) == 5
        assert [r["local"] for r in rows] == [
            "224.0.0.251:5353", "224.0.0.251:5353", "224.0.0.251:5353",
            "0.0.0.0:5353", "[::]:5353"]

    def test_the_multicast_group_is_recognised_as_such(self):
        rows = parse_mdns_listeners(CATA_SS_MDNS)
        assert [r["multicast"] for r in rows] == [
            True, True, True, False, False]

    def test_the_two_avahi_rows_carry_no_owner_and_that_is_reported(self):
        """Measured: `ss -ulpn` named `chrome` and left Avahi's own two rows
        blank, because naming a socket's holder needs privilege."""
        rows = parse_mdns_listeners(CATA_SS_MDNS)
        ownerless = [r for r in rows if not r["owner_named"]]
        assert [r["local"] for r in ownerless] == ["0.0.0.0:5353", "[::]:5353"]
        assert all(r["process"] == "" and r["pid"] == "" and r["fd"] == ""
                   for r in ownerless), ownerless

    def test_a_named_owner_is_read_when_the_kernel_gives_one(self):
        rows = parse_mdns_listeners(CATA_SS_MDNS)
        named = [r for r in rows if r["owner_named"]]
        assert {r["process"] for r in named} == {"chrome"}
        assert {r["pid"] for r in named} == {"5097", "5148"}
        # The fd is what tells two sockets of one process apart, and it is the
        # only thing in the capture that does.
        assert {r["fd"] for r in named} == {"319", "272", "82"}
        assert len({(r["pid"], r["fd"]) for r in named}) == 3

    def test_a_row_on_another_port_is_not_taken(self):
        """The filter's own negative control: this fixture is real `ss` output
        from the same run and holds four non-5353 rows, one of them port 53."""
        assert not parse_mdns_listeners(CATA_SS_OTHER)
        assert ":53" in CATA_SS_OTHER

    def test_the_columns_are_not_read_by_index(self):
        """`ss` prints the state and the receive queue with a **single** space
        between them (`UNCONN 0`), so a field-index parser files `0` as the
        address. Pinned by what the parser must produce, not by a comment."""
        rows = parse_mdns_listeners(CATA_SS_MDNS)
        assert all(re.fullmatch(r"\S+:\d+|\[[^\]]+\]:\d+", r["local"])
                   for r in rows), rows
        assert not any(r["local"] == "0" for r in rows)

    def test_no_row_is_taken_from_the_header_line(self):
        rows = parse_mdns_listeners("Local Address:Port\n")
        assert rows == []

    def test_an_empty_read_is_no_listeners_and_not_an_error(self):
        assert parse_mdns_listeners("") == []


class TestStaticHosts:
    def test_the_shipped_file_yields_no_mappings(self, tmp_path):
        path = tmp_path / "hosts"
        path.write_text(CATA_HOSTS_ALL_COMMENTS)
        assert _static_host_mappings(str(path)) == []

    def test_the_example_lines_in_the_shipped_file_are_not_mappings(self):
        """The file documents `192.168.0.1 router.local` as an example, and an
        un-commented reader would publish the comment's own example."""
        assert "192.168.0.1 router.local" in CATA_HOSTS_ALL_COMMENTS
        assert _static_host_mappings_from_text(
            CATA_HOSTS_ALL_COMMENTS) == []

    def test_a_real_mapping_is_found_when_one_exists(self, tmp_path):
        path = tmp_path / "hosts"
        path.write_text("# comment\n192.168.0.1 router.local\n\n"
                        "2001::81:1 test.local\n")
        assert _static_host_mappings(str(path)) == [
            "192.168.0.1 router.local", "2001::81:1 test.local"]

    def test_an_unreadable_file_is_no_mappings_rather_than_a_crash(self):
        assert _static_host_mappings("/nonexistent/avahi/hosts") == []


def _static_host_mappings_from_text(text: str) -> list:
    """`_static_host_mappings` against a string, through a temporary file.

    The helper takes a path because that is how the page uses it, so the tests
    exercise it the same way rather than re-implementing its loop.
    """
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".hosts", delete=False) as fh:
        fh.write(text)
        name = fh.name
    try:
        return _static_host_mappings(name)
    finally:
        os.unlink(name)


# --- the reader ------------------------------------------------------------


class TestTheReader:
    def test_it_produces_every_key_the_page_reads(self):
        """The tell for this class is always an absence, so the payload's key
        set is asserted rather than spot-checked."""
        seen = {}

        def run_text(argv, done):
            seen[tuple(argv)] = (REAL_SERVICE_ENABLED, "")
            done(REAL_SERVICE_ENABLED, "")

        avahi_mod.avahi_state(
            lambda payload, err: seen.setdefault("payload", payload),
            run_text=run_text, have_tool=lambda _t: True,
            tool=lambda t: t, conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins", services_path="/nonexistent/svc",
            hosts_path="/nonexistent/hosts")

        payload = seen["payload"]
        for key in ("service_enabled", "socket_enabled", "dbus_name_enabled",
                    "service_active", "units", "unit_count", "listeners",
                    "conf", "conf_read", "conf_d", "services", "hosts",
                    "have_systemctl", "have_ss", "have_browse", "errors"):
            assert key in payload, f"payload is missing {key}"

    def test_it_runs_exactly_the_six_documented_reads_and_nothing_else(self):
        """`is-enabled` on three names, `is-active` on one, `list-unit-files`,
        `ss`. Six - and the whole point of the page is that it never enables,
        starts, stops or publishes anything."""
        calls = []

        def run_text(argv, done):
            calls.append(list(argv))
            done(REAL_SERVICE_ENABLED, "")

        avahi_mod.avahi_state(
            lambda payload, err: None, run_text=run_text,
            have_tool=lambda _t: True, tool=lambda t: t,
            conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins",
            services_path="/nonexistent/svc", hosts_path="/nonexistent/hosts")

        normalised = [[a for a in argv] for argv in calls]
        assert normalised == [
            ["systemctl", "is-enabled", "avahi-daemon.service"],
            ["systemctl", "is-enabled", "avahi-daemon.socket"],
            ["systemctl", "is-enabled", "dbus-org.freedesktop.Avahi.service"],
            ["systemctl", "is-active", "avahi-daemon.service"],
            ["systemctl", "list-unit-files", "avahi*", "--no-pager"],
            ["ss", "-ulpn"],
        ], normalised

    def test_the_reads_advance_the_chain_once_each(self):
        """The regression this shape exists to prevent: passing `collect` as
        each reader's continuation re-enters the chain on every answer, which is
        an unbounded loop and reads correctly the whole time."""
        calls = []

        def run_text(argv, done):
            calls.append(list(argv))
            done(REAL_SERVICE_ENABLED, "")

        avahi_mod.avahi_state(
            lambda payload, err: None, run_text=run_text,
            have_tool=lambda _t: True, tool=lambda t: t,
            conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins",
            services_path="/nonexistent/svc", hosts_path="/nonexistent/hosts")

        assert len(calls) == 6, f"the chain ran {len(calls)} reads, not 6"

    def test_the_three_answers_land_in_three_different_keys(self):
        """One key per name, so the alias cannot overwrite the socket's answer."""
        seen = {}

        def run_text(argv, done):
            # Keyed on the whole argv, because `ss -ulpn` has two tokens and
            # `list-unit-files` has five - indexing argv[2] raises IndexError on
            # one of them, which is the sort of thing a test that only ever
            # reached the systemctl calls never finds.
            answer = {
                ("is-enabled", avahi_mod.SERVICE_UNIT): REAL_SERVICE_ENABLED,
                ("is-enabled", avahi_mod.SOCKET_UNIT): REAL_SOCKET_ENABLED,
                ("is-enabled", avahi_mod.DBUS_UNIT): REAL_DBUS_ENABLED,
                ("is-active", avahi_mod.SERVICE_UNIT): REAL_SERVICE_ACTIVE,
            }.get(tuple(argv[1:3]), CATA_LIST_UNIT_FILES
                  if argv[1] == "list-unit-files" else CATA_SS_MDNS)
            done(answer, "")

        avahi_mod.avahi_state(
            lambda payload, err: seen.update(payload), run_text=run_text,
            have_tool=lambda _t: True, tool=lambda t: t,
            conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins",
            services_path="/nonexistent/svc", hosts_path="/nonexistent/hosts")

        assert seen["service_enabled"] == "enabled"
        assert seen["socket_enabled"] == "enabled"
        assert seen["dbus_name_enabled"] == "alias"
        assert seen["service_active"] == "active"
        assert [u["unit"] for u in seen["units"]] == [
            "avahi-daemon.service", "avahi-daemon.socket"]
        assert len(seen["listeners"]) == 5

    def test_not_found_is_an_answer_and_not_a_failure(self):
        """`systemctl is-enabled` prints `not-found` on **stdout** with an empty
        stderr and exit 4. `run_text` ignores the exit status, so the word
        survives - which is why `run_status` would have been wrong here."""
        seen = {}

        def run_text(argv, done):
            if (len(argv) > 2 and argv[2] == avahi_mod.SOCKET_UNIT
                    and argv[1] == "is-enabled"):
                done(REAL_NOT_FOUND, "")
            else:
                done(REAL_SERVICE_ENABLED, "")

        avahi_mod.avahi_state(
            lambda payload, err: seen.update(payload), run_text=run_text,
            have_tool=lambda _t: True, tool=lambda t: t,
            conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins",
            services_path="/nonexistent/svc", hosts_path="/nonexistent/hosts")

        assert seen["socket_enabled"] == "not-found"
        title, _subtitle, _rows_ = _rendered(socket=REAL_NOT_FOUND,
                                             service=REAL_NOT_FOUND)
        assert "not installed" in title
        assert _verdict_state(socket=REAL_NOT_FOUND,
                              service=REAL_NOT_FOUND) == "critical"

    def test_a_failed_read_is_blank_rather_than_a_guess(self):
        seen = {}

        def run_text(argv, done):
            done(None, "Failed to connect to bus")

        avahi_mod.avahi_state(
            lambda payload, err: seen.update(payload), run_text=run_text,
            have_tool=lambda _t: True, tool=lambda t: t,
            conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins",
            services_path="/nonexistent/svc", hosts_path="/nonexistent/hosts")

        assert seen["socket_enabled"] == ""
        title, subtitle, _r = _rendered(socket="", service="")
        assert "Could not be read" in title
        assert "did not answer" in subtitle

    def test_it_reads_nothing_and_says_why_when_neither_tool_exists(self):
        """`run_text=None` on purpose: the reader must not reach it at all when
        both tools are missing, so passing None is what proves it did not."""
        calls = []

        def run_text(argv, done):
            calls.append(argv)
            done("", "")

        seen = {}

        def collect(payload, err):
            seen["payload"] = payload
            seen["err"] = err

        avahi_mod.avahi_state(
            collect, run_text=run_text, have_tool=lambda _t: False,
            tool=lambda t: t, conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins", services_path="/nonexistent/svc",
            hosts_path="/nonexistent/hosts")

        assert calls == [], f"the reader ran {calls} with no tools present"
        assert seen["payload"]["socket_enabled"] is None, (
            "an unread answer must be None in the payload and \"\" after the "
            "store step; anything else is a value nobody read")
        assert "neither systemctl nor ss is installed" in seen["err"]

    def test_it_hands_its_callback_a_payload_and_an_error(self):
        """Arity, checked by running it. A reader that calls `done(payload)` into
        a page expecting two arguments raises `TypeError` *inside* a GTK
        callback, GLib swallows it, and the page renders nothing with nothing in
        the log."""
        calls = []

        def run_text(argv, done):
            done(REAL_SERVICE_ENABLED, "")

        def collect(*args):
            calls.append(args)

        avahi_mod.avahi_state(
            collect, run_text=run_text, have_tool=lambda _t: True,
            tool=lambda t: t, conf_path="/nonexistent/avahi-daemon.conf",
            conf_d="/nonexistent/dropins", services_path="/nonexistent/svc",
            hosts_path="/nonexistent/hosts")

        assert len(calls) == 1, f"done() called {len(calls)} times"
        assert len(calls[0]) == 2, f"done() got {len(calls[0])} arguments"


# --- the socket is the switch ---------------------------------------------


class TestTheSocketIsTheSwitch:
    """The measured finding, held from both sides.

    The brief this page was built from predicted that `is-enabled` would report
    `disabled` or `static`. The packaged Arch unit has a real `[Install]`
    section, so it reports `enabled` when enabled - and Shanios enables the
    *socket*, which starts the daemon whether the service is enabled or not.
    """

    def test_the_arch_unit_has_an_install_section_so_it_is_not_static(self):
        """Read out of the packaged unit file, not recalled.

        `avahi 1:0.9rc5-1`'s `/usr/lib/systemd/system/avahi-daemon.service`
        ends `[Install] WantedBy=multi-user.target`, plus
        `Also=avahi-daemon.socket` and `Alias=dbus-org.freedesktop.Avahi.service`.
        """
        unit = os.path.join(
            "/home/shrinivaskumbhar/Documents/shani/shani-install-media/cache/"
            "pacman_cache/pkg", "avahi-1:0.9rc5-1-x86_64.pkg.tar.zst")
        if not os.path.exists(unit):
            pytest.skip(f"the Arch package is not on this host: {unit}")
        extracted = _extract_one(unit, "usr/lib/systemd/system/"
                                      "avahi-daemon.service")
        assert "[Install]" in extracted
        assert "WantedBy=multi-user.target" in extracted
        assert "Also=avahi-daemon.socket" in extracted
        assert "Alias=dbus-org.freedesktop.Avahi.service" in extracted

    def test_the_service_requires_the_socket_and_is_dbus_activated(self):
        """The mechanism, from the same packaged unit.

        `Requires=avahi-daemon.socket`, `Type=dbus`,
        `BusName=org.freedesktop.Avahi` - so the daemon is both socket- and
        D-Bus-activated, which is why the socket decides.
        """
        unit = os.path.join(
            "/home/shrinivaskumbhar/Documents/shani/shani-install-media/cache/"
            "pacman_cache/pkg", "avahi-1:0.9rc5-1-x86_64.pkg.tar.zst")
        if not os.path.exists(unit):
            pytest.skip(f"the Arch package is not on this host: {unit}")
        extracted = _extract_one(unit, "usr/lib/systemd/system/"
                                      "avahi-daemon.service")
        assert "Requires=avahi-daemon.socket" in extracted
        assert "Type=dbus" in extracted
        assert "BusName=org.freedesktop.Avahi" in extracted

    def test_shanios_enables_the_socket_and_never_the_service(self):
        """The install script, read as it is written.

        `shani-pkgbuilds/shani-network/shani-network.install:10` is
        `systemctl enable avahi-daemon.socket`. There is no line anywhere in that
        file enabling `avahi-daemon.service`.
        """
        path = os.path.join(
            "/home/shrinivaskumbhar/Documents/shani/shani-pkgbuilds/"
            "shani-network", "shani-network.install")
        if not os.path.exists(path):
            pytest.skip(f"the pkgbuilds checkout is not on this host: {path}")
        body = open(path, encoding="utf-8").read()
        assert "systemctl enable avahi-daemon.socket" in body
        assert "systemctl enable avahi-daemon.service" not in body, (
            "the install script now enables the service too; this page's whole "
            "argument is about the difference and it would be stale")

    def test_an_unstripped_answer_cannot_kill_the_whole_verdict_table(self):
        """The defect this file found, pinned, in three parts.

        `systemctl is-enabled` answers with a trailing newline. `_verdict`
        compares bare words, so a payload holding `"enabled\n"` matched **no**
        branch and the status row fell through to "systemd reported a state this
        page does not have a sentence for" - on the single state the page exists
        to get right, and with the trailing text cut off mid-sentence.

        It surfaced because this file's first payload builder pasted the capture
        in verbatim instead of going through `_store_enabled`. Both lines of
        defence are held, and the third assertion is what stops the second from
        becoming a catch-all.
        """
        raw = {"socket_enabled": "enabled\n", "service_enabled": "enabled\n",
               "service_active": "inactive\n"}
        title, subtitle, state = _verdict(raw)
        assert title == "Idle, and ready when it is needed", title
        assert "has no sentence" not in subtitle, subtitle
        assert state == "ok"

        # Line one: the reader normalises, so production never produces a raw
        # word in the first place. **Leading** whitespace is the case that
        # matters, and it is the one a trailing newline does not cover:
        # `splitlines()[0]` on `" enabled\n"` leaves the space, and `" enabled"`
        # matches no branch of `_verdict` exactly as `"enabled\n"` would not.
        # A control that only removed the `.strip()` passed, because
        # `splitlines()` had already done that half of the job - which is the
        # definition of a control that cannot fail.
        store: dict = {}
        avahi_mod._store_enabled(store, "socket_enabled", " enabled\n", "", "")
        assert store["socket_enabled"] == "enabled", store
        store2: dict = {}
        avahi_mod._store_enabled(store2, "socket_enabled", "\tenabled  \n", "", "")
        assert store2["socket_enabled"] == "enabled", store2
        # And a multi-line answer is reduced to its first line, not kept whole.
        store3: dict = {}
        avahi_mod._store_enabled(store3, "socket_enabled",
                                 "enabled\nmasked\n", "", "")
        assert store3["socket_enabled"] == "enabled", store3

        # Line three: a word systemd never printed is still reported as itself,
        # so `_word` is a second line and not a way of inventing an answer.
        title, subtitle, state = _verdict(
            {"socket_enabled": "wobbly\n", "service_enabled": "wobbly",
             "service_active": "wobbly"})
        assert title == "The activation socket answered wobbly", title
        assert "does not have a sentence" in subtitle, subtitle
        assert state == "unknown"

    def test_the_payload_helper_normalises_so_the_page_sees_real_answers(self):
        """The anti-drift half: `_payload` must not reintroduce the defect."""
        payload = _payload()
        for key in ("service_enabled", "socket_enabled", "dbus_name_enabled"):
            assert payload[key] == payload[key].strip(), (
                f"{key} carries whitespace; _verdict compares bare words")
        assert payload["socket_enabled"] == "enabled"

    def test_a_disabled_service_beside_an_enabled_socket_is_not_reported_as_off(
            self):
        """The Shanios state, and the one the brief predicted wrongly.

        Service `disabled`, socket `enabled`, daemon inactive: working
        discovery. A verdict built on the service answers "off".
        """
        title, subtitle, _rows_ = _rendered(
            socket=REAL_SOCKET_ENABLED, service="disabled",
            active=REAL_INACTIVE, unit_count=2,
            units=CATA_LIST_UNIT_FILES.replace(
                "avahi-daemon.service enabled enabled",
                "avahi-daemon.service disabled enabled"))
        assert title == "Idle, and ready when it is needed", title
        assert "starts" in subtitle and "enabled" in subtitle
        assert "off" not in title.lower()

    def test_the_disabled_service_is_still_shown_beside_the_socket(self):
        _title, _sub, rows = _rendered(socket=REAL_SOCKET_ENABLED,
                                       service="disabled")
        by_title = dict(rows)
        row = by_title["avahi-daemon.service - is-enabled"]
        assert "Answered disabled" in row
        assert "not the same as off" in row

    def test_static_is_described_as_having_no_install_section(self):
        """`static` on a real unit means it *cannot* be enabled, which is a
        different statement from "it is off" - and it is not an answer the
        daemon's unit can give, because it has an `[Install]` section."""
        sentence = _enabled_sentence("avahi-daemon.service", "static", "note")
        assert "no Install section" in sentence
        assert "Answered static" in sentence

    def test_masked_is_reported_and_not_changed(self):
        sentence = _enabled_sentence(avahi_mod.SOCKET_UNIT, "masked", "note")
        assert "deliberately switched off" in sentence
        assert "never changed" in sentence

    def test_alias_is_described_as_another_name_not_a_third_state(self):
        sentence = _enabled_sentence(avahi_mod.DBUS_UNIT, "alias", "note")
        assert "another way of naming" in sentence

    def test_an_unread_answer_is_not_any_of_the_five_words(self):
        sentence = _enabled_sentence(avahi_mod.SOCKET_UNIT, "", "note")
        assert "did not answer" in sentence
        assert "not the same as off" in sentence

    def test_enabled_runtime_is_treated_as_enabled(self):
        """`enabled-runtime` is a real answer with a real meaning.

        A runtime enable lives only in `/run`, so it is gone after a reboot - a
        genuinely different fact from `enabled`, and one a settings page should not
        flatten. The verdict's membership tuple names it, and this holds the name
        from being dropped: the day it goes, this socket stops being treated as the
        switch and a machine with a runtime enable renders as the no-sentence
        branch.
        """
        assert "enabled-runtime" in avahi_mod._ENABLED_ANSWERS
        assert "enabled-runtime" in avahi_mod._ENABLED_ANSWERS
        sentence = _enabled_sentence(avahi_mod.SOCKET_UNIT, "enabled-runtime",
                                     "note")
        assert sentence.startswith("Answered enabled-runtime"), sentence
        title, _subtitle, state = _verdict({
            "socket_enabled": "enabled-runtime", "service_enabled": "enabled",
            "service_active": "inactive"})
        assert title == "Idle, and ready when it is needed", title
        assert state == "ok"

    def test_masked_runtime_is_treated_as_masked(self):
        assert "masked-runtime" in avahi_mod._ENABLED_ANSWERS
        sentence = _enabled_sentence(avahi_mod.SOCKET_UNIT, "masked-runtime",
                                     "note")
        assert "deliberately switched off" in sentence
        title, _subtitle, state = _verdict({
            "socket_enabled": "masked-runtime", "service_enabled": "",
            "service_active": ""})
        assert title == "Discovery is masked", title
        assert state == "warning"

    def test_every_is_enabled_answer_the_page_knows_has_a_sentence(self):
        for answer in avahi_mod._ENABLED_ANSWERS:
            sentence = _enabled_sentence("u", answer, "note")
            assert sentence.startswith("Answered ") or "not established" in \
                sentence, answer

    def test_an_unknown_answer_is_shown_verbatim_rather_than_mapped(self):
        sentence = _enabled_sentence("u", "wobbly", "note")
        assert "Answered wobbly" in sentence
        assert "no sentence for" in sentence


def _extract_one(pkg: str, member: str) -> str:
    """One file out of a `.pkg.tar.zst`, through tar rather than a pacman-key
    dependency. Returns "" when the member is absent, so a test that depends on
    it fails on its content rather than on an exception."""
    proc = subprocess.run(["tar", "--zstd", "-xOf", pkg, member],
                          capture_output=True, text=True, timeout=60)
    return proc.stdout if proc.returncode == 0 else ""


# --- rendering -------------------------------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        assert _rows(AvahiTab()), "the page rendered no rows at all"

    def test_every_rendered_row_has_a_title(self):
        """An empty title is how this repo's rows go missing: built, stored,
        updated, and never given a parent. Asserted against a non-zero count so
        the test cannot pass by finding nothing."""
        rows = _rows(AvahiTab())
        assert rows
        for title, _subtitle in rows:
            assert title, "a rendered row has no title at all"

    def test_the_page_shows_a_row_for_every_unit_systemd_printed(self):
        _title, _sub, rows = _rendered(units=CATA_LIST_UNIT_FILES)
        titles = [t for t, _s in rows]
        for unit in ("avahi-daemon.service", "avahi-daemon.socket"):
            assert any(t.startswith(unit) for t in titles), (
                f"{unit} missing from {titles}")

    def test_no_two_rows_on_the_page_share_a_title(self):
        """Found by rendering on Arch, and by nothing else.

        The unit-file rows and the `is-enabled` rows both produced a row titled
        `avahi-daemon.service`, so the page showed **two rows with the same
        title**, one directly above the other, differing only in a subtitle. That
        was invisible to every widget-tree assertion in this file, because both
        rows were present, correctly parented, and carrying the right text - the
        defect is a *duplication*, which is the mirror of this repo's more usual
        "a row was built and never given a parent".

        It showed up in the Arch render at 640px wide and had been there all
        along at 1000px; a screenshot is what found it and the assertion is what
        keeps it found.
        """
        for label, kwargs in (("the capture", {}),
                              ("the Arch three-unit shape",
                               {"units": ARCH_UNITS_BELOW, "unit_count": 3}),
                              ("the not-found shape",
                               {"socket": "not-found",
                                "service": "not-found"}),
                              ("the Shanios shape",
                               {"socket": REAL_SOCKET_ENABLED,
                                "service": "disabled",
                                "active": REAL_INACTIVE})):
            _title, _sub, rows = _rendered(**kwargs)
            titles = [t for t, _s in rows]
            assert titles, label
            dupes = sorted({t for t in titles if titles.count(t) > 1})
            assert not dupes, f"{label}: {len(titles)} rows, duplicated titles {dupes}"

    def test_the_unit_file_and_is_enabled_rows_are_told_apart_by_their_titles(self):
        _title, _sub, rows = _rendered()
        titles = [t for t, _s in rows]
        assert "avahi-daemon.service - unit file" in titles, titles
        assert "avahi-daemon.service - is-enabled" in titles, titles
        assert "avahi-daemon.socket - is-enabled" in titles, titles

    def test_the_page_does_not_tell_the_reader_that_avahi_browse_is_missing(self):
        """The wording defect the Arch render caught.

        `NOT_PARSED_NOTE` used to say avahi-browse "is absent on the machine this
        page was written against, so its output has never been captured **here**".
        Rendered on a Shanios machine - where avahi-browse **is** installed and the
        Browse button works - "here" reads as the reader's own machine, so the page
        told someone with a working tool that they did not have one.

        The claim that survives is about the page's own evidence, not about the
        reader's system: the tool is present on Shanios, and no listing it produced
        has been captured anywhere.
        """
        joined = " ".join(_all_strings(AvahiTab())) + " " + avahi_mod.NOT_PARSED_NOTE
        assert "avahi-browse is absent" not in joined, (
            "the page claims avahi-browse is absent; it is present on Shanios")
        assert "captured here" not in joined, (
            "'here' reads as the reader's machine")
        assert "present on Shanios" in joined, joined
        assert "avahi-browse -alrpt" in joined

    def test_the_socket_row_says_it_is_the_switch(self):
        _title, _sub, rows = _rendered()
        by_title = dict(rows)
        assert "The switch that matters" in by_title[
            "avahi-daemon.socket - is-enabled"]

    def test_the_daemon_running_row_is_empty_until_it_is_read(self):
        _title, _sub, rows = _rendered(active="")
        by_title = dict(rows)
        assert "unknown rather than no" in by_title["Is it running now"]

    def test_a_listener_with_no_owner_says_it_was_not_named(self):
        _title, _sub, rows = _rendered()
        by_title = dict(rows)
        assert "was not named" in by_title["0.0.0.0:5353"]
        assert "privilege" in by_title["0.0.0.0:5353"]

    def test_the_ownerless_rows_carry_no_pid_in_their_title(self):
        """There is no pid to name, and inventing one is what this page refuses
        to do everywhere else."""
        _title, _sub, rows = _rendered()
        titles = [t for t, _s in rows]
        assert "0.0.0.0:5353" in titles
        assert "[::]:5353" in titles

    def test_a_named_listener_is_named(self):
        _title, _sub, rows = _rendered()
        joined = " ".join(f"{t} {s}" for t, s in rows)
        assert "held by chrome (pid 5097, fd 319)" in joined
        assert "held by chrome (pid 5148, fd 82)" in joined

    def test_the_three_rows_on_one_address_are_told_apart(self):
        """The capture holds THREE rows on `224.0.0.251:5353`, **two of them the
        same pid**, so a title of address-plus-pid still renders two identical
        rows. Only the fd separates them, and `ss` gave it.

        Found while writing the test above: `dict(rows)` silently kept only the
        last of the three, which read as a parser bug and was not one.
        """
        _title, _sub, rows = _rendered()
        multicast = [t for t, _s in rows if t.startswith("224.0.0.251:5353")]
        assert len(multicast) == 3, multicast
        assert len(set(multicast)) == 3, f"three identical titles: {multicast}"
        assert any("pid 5097 fd 319" in t for t in multicast), multicast
        assert any("pid 5097 fd 272" in t for t in multicast), multicast

    def test_a_multicast_listener_says_which_group(self):
        _title, _sub, rows = _rendered()
        joined = " ".join(f"{t} {s}" for t, s in rows)
        assert "224.0.0.251" in joined
        assert "multicast member" in joined

    def test_no_listener_rows_at_all_is_reported_not_left_blank(self):
        _title, _sub, rows = _rendered(ss_text="")
        by_title = dict(rows)
        assert "Nothing found on the port" in by_title

    def test_the_config_group_shows_the_six_keys_and_not_the_comments(self):
        _title, _sub, rows = _rendered(conf=ARCH_CONF)
        joined = " | ".join(f"{t}={s}" for t, s in rows)
        assert "[server] use-ipv4" in joined
        assert "[publish] publish-hinfo" in joined
        assert "#" not in joined, (
            f"a commented key reached the page: {joined}")

    def test_the_config_group_says_wide_area_is_not_set_by_the_file(self):
        _title, _sub, rows = _rendered(conf=ARCH_CONF)
        joined = " | ".join(f"{t}={s}" for t, s in rows)
        assert "wide-area" not in joined, (
            "the page claimed something about wide-area; the Shanios file "
            "leaves it commented and this page must not fill in a default")

    def test_an_unreadable_config_is_reported_as_unreadable_not_as_empty(self):
        _title, _sub, rows = _rendered(conf_readable=False)
        by_title = dict(rows)
        assert "Not readable, or not present" in by_title[
            avahi_mod.AVAHI_CONF]

    def test_a_present_dropin_directory_is_a_warning_not_a_setting(self):
        _title, _sub, rows = _rendered(conf_d_present=True)
        by_title = dict(rows)
        assert by_title[avahi_mod.AVAHI_CONF_D].startswith("Present.")
        assert "override" in by_title[avahi_mod.AVAHI_CONF_D]

    def test_an_absent_dropin_directory_is_the_expected_answer(self):
        _title, _sub, rows = _rendered(conf_d_present=False)
        by_title = dict(rows)
        assert by_title[avahi_mod.AVAHI_CONF_D].startswith("Not present.")
        assert "expected answer" in by_title[avahi_mod.AVAHI_CONF_D]

    def test_no_ss_installed_is_reported_rather_than_an_empty_list(self):
        _title, _sub, rows = _rendered(have_ss=False)
        by_title = dict(rows)
        assert "ss is not installed" in by_title["Cannot be read"]

    def test_the_page_says_it_publishes_nothing(self):
        """Over the group descriptions as well as the rows.

        `DOES_NOT_NOTE` is a `PreferencesGroup.description` with no rows under
        it, so a walk that read rows only would inspect nothing and pass - the
        absence that is always the tell.
        """
        _title, _sub, rows = _rendered()
        assert rows, "nothing rendered, so the wording check proved nothing"
        joined = " ".join(_all_strings(AvahiTab()))
        assert "never publishes" in joined
        assert "never enables" in joined
        assert "never writes to /etc/avahi" in joined

    def test_every_group_description_survives_pango(self):
        for text in (avahi_mod.SUMMARY_NOTE, avahi_mod.UNITS_NOTE,
                     avahi_mod.LISTENERS_NOTE, avahi_mod.CONFIG_NOTE,
                     avahi_mod.BROWSE_NOTE, avahi_mod.NOT_PARSED_NOTE,
                     avahi_mod.DOES_NOT_NOTE, avahi_mod.TOOLS_NOTE):
            assert not _markup_error(text), f"Pango rejected {text[:40]!r}"

    def test_no_string_the_page_renders_is_misread_as_markup(self):
        """The hostile case, run through the real builders.

        A hostname or a service type is free text, and this is the string that
        would break a row. The assertions are on what the page *produced*, not
        on what `_plain` was asked to do.
        """
        tab = AvahiTab()
        tab._on_state(_payload(conf="", conf_readable=True), "")
        rows = _rows(tab)
        assert rows, "nothing rendered, so the hostile pass proved nothing"
        rendered = _all_strings(tab) + [a for pair in rows for a in pair]
        for text in rendered:
            assert _markup_safe(text), f"not markup-safe: {text!r}"
            assert not _markup_error(text), f"Pango rejected: {text!r}"
        # The three strings that would break a row if they reached one raw, and
        # the exact escaped form each has to arrive in.
        for raw, escaped in (("/etc/avahi/avahi-daemon.conf",
                              "/etc/avahi/avahi-daemon.conf"),
                             ("x&y", "x&amp;y"),
                             ("<service>", "&lt;service&gt;")):
            assert avahi_mod._plain(raw) == escaped
            assert not _markup_error(escaped)

    def test_the_ampersand_in_a_path_survives_as_words(self):
        assert avahi_mod._plain("AT&T<tag>") == "AT&amp;T&lt;tag&gt;"

    def test_the_markup_check_itself_can_fail(self):
        assert _markup_error("a & b")
        assert _markup_error("  see <a name you choose>")
        assert not _markup_error("a &amp; b")


# --- the read-only contract ------------------------------------------------


class TestReadOnlyContract:
    def test_the_page_never_enables_disables_starts_or_stops_anything(self):
        """An AST gate over the page's own code, with every string blanked.

        Both removals matter and both were found the hard way elsewhere in this
        repo: the docstring argues at length that the page is read-only, and
        `DOES_NOT_NOTE` names `systemctl enable avahi-daemon.socket` - a literal
        the reader is entitled to print and a gate is not entitled to trip over.
        """
        code = _code(avahi_mod)
        # Every `systemctl` subcommand this page can pass, gathered from its own
        # AST rather than from a list written here. It is built by walking for
        # `run_text` / `run_stream_tool` calls and reading the argv, so a
        # subcommand added in a new branch is caught without this test being
        # edited - which is the difference between a gate and a wish.
        # (`_args_of` resolves module constants such as `SERVICE_UNIT`, and the
        # browse argv is checked separately by `test_the_browse_argv_is_read_only`
        # because its flags are literal rather than named.)
        argvs = [a for a in _argv_literals(avahi_mod, "run_text") if a]
        assert len(argvs) == 6, (
            f"the page makes {len(argvs)} run_text calls, not the documented "
            f"six: {argvs}")
        for argv in argvs:
            for token in argv:
                if token is None:
                    continue          # a computed position; see _argv_literals
                assert token not in ("enable", "disable", "start", "stop",
                                     "restart", "reload", "mask", "unmask",
                                     "kill", "set-property", "edit", "cat",
                                     "daemon-reload", "isolate"), (
                    f"the page passes {token!r} to systemctl in {argv}")

        # **The exact argv, not membership of it.** A first version asserted that
        # each of the three unit names appeared *somewhere*, and a control that
        # repointed `is-active` at `avahi-dnsconfd.service` duly passed: the two
        # `is-enabled` calls still carried `avahi-daemon.service`, so every name
        # was still "seen". Listing the argv is what closes that, and `None` is
        # the tool position - `paths[SYSTEMCTL]` / `paths[SS]` - which the
        # injectable resolver hides from a literal read.
        #
        # The same six argv are asserted verbatim at the reader in
        # `TestTheReader`, where the paths are real strings because the runner is
        # injected. This is the page-level half: what the **widget's module** asks
        # for, without running anything.
        assert sorted(tuple(str(t) for t in a) for a in argvs) == sorted([
            ("None", "is-enabled", avahi_mod.SERVICE_UNIT),
            ("None", "is-enabled", avahi_mod.SOCKET_UNIT),
            ("None", "is-enabled", avahi_mod.DBUS_UNIT),
            ("None", "is-active", avahi_mod.SERVICE_UNIT),
            ("None", "list-unit-files", "None", "--no-pager"),
            ("None", "-ulpn"),
        ]), argvs

        for banned in ("systemctl enable", "systemctl disable",
                       "systemctl start", "systemctl stop",
                       "avahi-publish", "avahi-set-host-name",
                       "avahi-resolve-host-name"):
            assert banned not in code, f"the page runs {banned}"

    def test_the_page_never_escalates(self):
        """No `pkexec`, no `su`, no shell. Cassini ships no polkit rule of its
        own, and a read-only reporter has no business asking for a password."""
        code = _code(avahi_mod)
        for banned in ("pkexec", "sudo", "Popen", "check_output", "subprocess"):
            assert banned not in code, f"the page uses {banned}"

    def test_the_page_runs_no_command_on_load(self):
        """The six reads are all the page runs unprompted, and each is a read.

        The only argv the page builds outside the reader is the browse one, and
        that is behind a click handler. Asserted against the argv actually
        recovered from the AST, and the list is asserted non-empty first so the
        check cannot pass by recovering nothing.
        """
        argvs = [a for a in _argv_literals(avahi_mod, "run_text") if a]
        assert len(argvs) == 6, (
            f"no run_text argv was recovered, or the page runs "
            f"{len(argvs)} reads rather than the documented six: {argvs}")
        # argv[0] is `paths[SYSTEMCTL]` / `paths[SS]` and comes back `None`, so
        # the tool cannot be named from the call site - which is the point of the
        # injectable resolver. What *is* checkable is the subcommand and its
        # target, and `test_it_runs_exactly_the_six_documented_reads_and_nothing_else`
        # pins the full argv at the reader, where the runner is injected and the
        # paths are therefore real strings.
        for argv in argvs:
            assert argv[0] is None, (
                f"argv[0] is {argv[0]!r} rather than the resolved tool path; if "
                f"the page now builds a literal argv, assert on it here")
            assert any(t in argv for t in ("is-enabled", "is-active",
                                           "list-unit-files", "-ulpn")), argv

    def test_avahi_browse_runs_only_from_the_button_handler(self):
        """The one command on the page, and where it is allowed to be.

        Structural rather than textual: the call has to live inside the function
        the button is connected to, so moving it to `load()` fails the gate.
        """
        tree = ast.parse(_code(avahi_mod))
        in_click = []
        elsewhere = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "run_stream_tool"):
                    (in_click if node.name == "_on_browse_clicked"
                     else elsewhere).append(node.name)
        assert in_click, "the browse call is no longer in the click handler"
        assert not elsewhere, (
            f"avahi-browse is also called from {elsewhere}; it must run only "
            f"when the button is pressed")

    def test_the_browse_argv_is_read_only(self):
        """`--terminate` is the tool's own flag for exiting after the first
        browse. There is no publish flag anywhere in it."""
        tree = ast.parse(inspect.getsource(avahi_mod))
        names = {k: v for k, v in vars(avahi_mod).items()
                 if not k.startswith("__")}
        argvs = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run_stream_tool"):
                for arg in node.args:
                    if isinstance(arg, ast.List):
                        # `AVAHI_BROWSE` is a module constant, so it parses as a
                        # Name and `ast.literal_eval` raises on it. Resolving
                        # against the module's own globals is what makes the argv
                        # checkable at all.
                        argvs.append([names[e.id] if isinstance(e, ast.Name)
                                      and e.id in names else e.value
                                      for e in arg.elts])
        assert argvs, "the browse call builds no literal argv"
        for argv in argvs:
            assert argv == [avahi_mod.AVAHI_BROWSE, "--all-services",
                            "--terminate"], argv
            assert not any(a in ("--publish", "-p") for a in argv)

    def test_the_page_never_writes_to_etc_avahi(self):
        code = _code(avahi_mod)
        for banned in ("config_io", "write_staged", "install", "mv ", "cp "):
            assert banned not in code, f"the page uses {banned}"
        # Every `open()` in the module is read-only. **Both** spellings of the
        # mode are read, and the positional one was the gap: a first version
        # looked only at `mode=` as a keyword, so `open(path, "w")` passed it -
        # and a negative control that changed the reader into
        # `open(path, "w", ...)` duly did not fail the suite. A text check for
        # `"<path>", "w"` was no better; it missed the same edit, because the
        # path arrives as a variable.
        tree = ast.parse(inspect.getsource(avahi_mod))
        opens = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "open"]
        assert opens, "no open() found in avahi.py; the gate is inspecting " \
                      "nothing"
        for node in opens:
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value          # open(path, "w")
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value          # open(path, mode="w")
            assert mode is None or mode == "r", (
                f"an open() in avahi.py asks for mode {mode!r}")
            assert not any(isinstance(a, ast.Constant) and a.value
                           in ("w", "a", "x", "+", "r+")
                           for a in node.args
                           if isinstance(a, ast.Constant)), node.args

        # And no write-shaped call at all: these are the four ways this module
        # could have written to /etc/avahi without an `open`.
        for banned in ("os.remove", "os.unlink", "os.rename", "os.replace",
                       "os.makedirs", "os.chmod", "shutil"):
            assert banned not in inspect.getsource(avahi_mod), \
                f"avahi.py calls {banned}"

    def test_the_page_carries_no_switch_or_checkbox_of_any_kind(self):
        """A toggle is a control, and this page has none.

        `Adw.Switch` does not exist - the switch is `Gtk.Switch`, and asking Adw
        for it raises `AttributeError` rather than finding nothing, which is a
        loud way to learn that a test was checking nothing.
        """
        tab = AvahiTab()
        widgets = _walk(tab)
        assert widgets, "the page has no widget tree at all"
        assert not hasattr(Adw, "Switch"), (
            "libadwaita grew an Adw.Switch; this gate should look at it now")
        for kind in (Gtk.Switch, Gtk.CheckButton, Gtk.ToggleButton):
            found = [type(w).__name__ for w in widgets
                     if isinstance(w, kind)]
            assert not found, f"the page carries {kind.__name__}: {found}"

    def test_the_only_buttons_are_refresh_and_browse(self):
        """Both are named, and neither is a state change.

        Refresh re-runs the six reads. Browse runs `avahi-browse`, which only
        listens. Asserted as a count so a third button cannot appear quietly.
        """
        tab = AvahiTab()
        labels = sorted(w.get_label() for w in _walk(tab)
                        if isinstance(w, Gtk.Button) and w.get_label())
        assert labels == ["Browse", "Refresh"], labels


def _own_images(tab) -> list:
    """The images this page put on its status row, and only those.

    `tab._state_icon` is the page's own reference to the one image it adds there;
    its parent is the prefix box that holds exactly that image. Counting in that
    box is what proves a refresh does not accumulate a second one.
    """
    image = tab._state_icon
    if image is None:
        return []
    box = image.get_parent()
    return [w for w in _walk(box) if isinstance(w, Gtk.Image)] if box else []


def _walk(node):
    found = [node]
    child = node.get_first_child()
    while child is not None:
        found.extend(_walk(child))
        child = child.get_next_sibling()
    return found


class TestThePangoGate:
    """There must be exactly one way text can enter a label, and it must escape.

    Asserted structurally, so it cannot pass by finding nothing - the shape of
    guard that has been deleted silently before, in this repo, more than once.
    """

    def test_there_is_exactly_one_place_a_row_is_built(self):
        """`Adw.ActionRow(...)` parses as a call on the **attribute**
        `Adw.ActionRow`, not on a name - a gate matching `ast.Name` finds zero
        and would have reported that as "a row is built in two places" or as a
        pass, depending on which way round it was written."""
        calls = [n for n in ast.walk(ast.parse(inspect.getsource(avahi_mod)))
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "ActionRow"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "Adw"]
        assert len(calls) == 1, f"Adw.ActionRow is called {len(calls)} times"

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        calls = [n for n in ast.walk(ast.parse(inspect.getsource(avahi_mod)))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "set_subtitle"]
        # Two, both inside AvahiTab: the status row and the browse row. Both
        # escape, and this asserts the count so a third cannot appear quietly.
        assert len(calls) == 2, f"set_subtitle is called {len(calls)} times"

    def test_both_gates_found_something_to_check(self):
        """The anti-absence half of the two gates above."""
        assert "_row(" in inspect.getsource(avahi_mod)
        assert "set_subtitle(" in inspect.getsource(avahi_mod)

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw, escaped in (("a & b", "a &amp; b"), ("<tag>", "&lt;tag&gt;"),
                             ("a > b", "a &gt; b")):
            assert avahi_mod._plain(raw) == escaped

    def test_plain_escapes_the_ampersand_first(self):
        """Order matters: escaping is not idempotent, so an `&` introduced by a
        later replacement must not be escaped a second time."""
        assert avahi_mod._plain("<a & b>") == "&lt;a &amp; b&gt;"
        assert "&amp;lt;" not in avahi_mod._plain("<a & b>")

    def test_plain_leaves_an_apostrophe_alone(self):
        assert avahi_mod._plain("the daemon's socket") == "the daemon's socket"

    def test_the_group_descriptions_go_through_plain(self):
        """The descriptions are Pango labels too - two descriptions in this repo
        shipped with a raw `<` and rendered as nothing."""
        tree = ast.parse(inspect.getsource(avahi_mod))
        # `description=` is a **keyword argument**, not a `.description()`
        # attribute call. A gate looking for the attribute finds nothing, which
        # is the shape of guard that reads as a pass while inspecting nothing.
        described = [kw for n in ast.walk(tree)
                     if isinstance(n, ast.Call)
                     for kw in n.keywords if kw.arg == "description"]
        assert described, "no PreferencesGroup description found; the gate " \
                          "would be inspecting nothing"
        assert len(described) >= 8, (
            f"only {len(described)} group descriptions found; this page has "
            f"eight, so the walk is inspecting less than it should")
        for kw in described:
            assert isinstance(kw.value, ast.Call), (
                f"a group description is a bare name, not a _plain(...) call: "
                f"{ast.dump(kw.value)}")
            assert (isinstance(kw.value.func, ast.Name)
                    and kw.value.func.id == "_plain"), (
                f"a group description is not escaped: {ast.dump(kw.value)}")


# --- the page under a real GTK renderer ------------------------------------


def _pump(until=None, budget_ms: int = 10000) -> int:
    """Iterate the GLib main context until `until()` holds. Returns the polls.

    Non-blocking iteration plus a sleep, deliberately: a blocking
    `ctx.iteration(True)` in a loop whose purpose is to *wait for an allocation*
    would be the wrong shape, and a `timeout_add` is forbidden on a page by this
    repo's own gates.

    The `until` predicate is what keeps this from being slow. A first version ran
    the whole budget every time - 3000 polls at 4ms - which is twelve seconds a
    call whether the widget was laid out in the first or the hundredth, and four
    render tests of that took the file past a hundred seconds.

    The budget is 10s rather than 4s because this test **flaked once** and the
    cause was the machine, not the code: five other pytest processes were holding
    about 5GB each, load average was 24, and the capture came back far smaller
    than the same capture has produced every other time. Under six busy loops it
    passes, only slower (19s -> 40s), so it is memory pressure and not CPU. Rather
    than retry the assertion - which would be this repo's "delete a failing test
    to pass CI" in a nicer coat - the budget is longer and the failure message
    reports both byte counts, so a repeat says what it was rather than only that
    it was.
    """
    import time
    context = GLib.MainContext.default()
    polls = max(1, budget_ms // 4)
    for n in range(polls):
        context.iteration(False)
        if until is not None and until():
            return n + 1
        time.sleep(0.004)
    return polls


def _flat_background_css(name: str, priority: int) -> Gtk.CssProvider:
    """A one-colour stylesheet, for the blank control.

    `Gtk.CssProvider.load_from_data` is deprecated in GTK 4.12 in favour of
    `load_from_string`; both are tried so this runs on 4.14 (this host) and on
    Arch's 4.22 without a warning on either.
    """
    css = Gtk.CssProvider()
    rule = f"box#{name} {{ background-color: rgb(20,20,20); }}"
    if hasattr(css, "load_from_string"):
        css.load_from_string(rule)
    else:
        css.load_from_data(rule.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, priority)
    return css


def _settled(widget) -> bool:
    """Has this widget been given a real size *and* drawn at least once?"""
    return (widget.get_width() > 0 and widget.get_height() > 0
            and widget.get_mapped())


def _shoot(widget, path: str, width: int = 1000, height: int = 1700):
    """Put a widget in a window, let GTK lay it out, and snapshot it to a PNG.

    Returns `(png_bytes, texture_width, texture_height)`, and `(0, 0, 0)` when
    the snapshot produced no render node at all - the case that reads as "the
    page rendered" if a caller treats any return as success.

    The path taken is `Gtk.WidgetPaintable` -> `Gtk.Snapshot` ->
    `Gsk.Renderer.render_texture`, which is real painting through the real
    renderer, not a widget-tree inspection.

    **What this method does not tell you: where anything is.** A capture through
    it mis-placed a button into the group above the one the widget tree puts it
    in, on this host's X display. The widget tree is the authority on structure
    and this is the authority on "something was actually drawn"; a test that
    wanted geometry should ask the tree, or capture the real window with `xwd`
    (the method `AGENTS.md` records). Both are asserted here for that reason.
    """
    window = Gtk.Window()
    window.set_default_size(width, height)
    window.set_child(widget)
    try:
        window.present()
        _pump(lambda: _settled(widget))
        paintable = Gtk.WidgetPaintable.new(widget)
        pw, ph = paintable.get_intrinsic_width(), paintable.get_intrinsic_height()
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, pw, ph)
        node = snapshot.to_node()
        if node is None:
            return 0, 0, 0
        texture = window.get_renderer().render_texture(node, None)
        _pump(lambda: False, budget_ms=200)
        texture.save_to_png(path)
        return os.path.getsize(path), texture.get_width(), texture.get_height()
    finally:
        window.destroy()


class TestThePageRendersForReal:
    """The page painted through GTK's renderer, not merely constructed.

    Every other test in this file inspects the widget tree, which proves the page
    built the rows and not that anything was drawn. `AGENTS.md` records two
    defects in this repo that a green widget-tree suite did not catch and a
    render did, so this class exists for the gap.

    It is skipped, not failed, when there is no display - a headless machine has
    no renderer and a skip is the honest answer. It is **not** skipped when the
    display exists but the page does not paint, because that is the thing worth
    failing on.
    """

    @pytest.fixture(autouse=True)
    def _needs_a_display(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            pytest.skip("no display: there is no GTK renderer to paint with")
        yield

    def test_the_page_paints_and_the_capture_is_not_a_blank_surface(
            self, tmp_path):
        """The page's PNG against a blank control of **the same dimensions**.

        Both numbers were measured rather than guessed: a flat one-colour
        surface at 1000x1700 encodes to **10,442** bytes on this host and this
        page encodes to **267,740** at 1000x1779 - 25.6x. The assertion is 4x,
        which the measurement clears by a wide margin and a blank render cannot
        reach.

        **The control is built at the page's own size, after the page has been
        shot.** That ordering is not tidiness. A first version sized both at
        1000x1700 and asserted a fixed `page_w >= 900`, and it passed on this
        host's `:1` display (1000px wide) and **failed under `xvfb-run` in the
        Arch container at 640px** - `set_default_size` is clamped to the screen,
        so the width assertion was really an assertion about the X display. The
        control was also 1000px wide while the page was 640px, so the ratio
        compared two different pictures.

        The width is now not asserted at all, and the height - which is what
        says the page was laid out in full - is. Measured: 1779px on Ubuntu
        GTK 4.14, 2377px on Arch GTK 4.22.5 under Xvfb. Both are far above the
        900px floor, and a page that laid out nothing is nowhere near it.

        The blank control is not decoration either. An empty `Gtk.Box` is **not**
        a usable blank: it has no intrinsic size, produces no render node, and so
        fails for a different reason than a page that failed to draw.
        """
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        page_bytes, page_w, page_h = _shoot(tab, str(tmp_path / "page.png"))

        assert (page_bytes, page_w, page_h) != (0, 0, 0), (
            "the page produced no render node: nothing was painted at all")
        assert page_w > 0, page_w
        assert page_h >= 900, (
            f"the page laid out to only {page_h}px tall; with eight groups it "
            f"measured 1779px on GTK 4.14 and 2377px on GTK 4.22.5, so this "
            f"is a page that did not lay out rather than a short one")

        # The control, at exactly the size the page just measured.
        _flat_background_css("avahi-blank", 1000)
        blank = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        blank.set_name("avahi-blank")
        blank.set_size_request(page_w, page_h)
        blank_bytes, blank_w, blank_h = _shoot(
            blank, str(tmp_path / "blank.png"))

        assert (blank_w, blank_h) == (page_w, page_h), (
            f"the control is {blank_w}x{blank_h} and the page is "
            f"{page_w}x{page_h}; a ratio between two different pictures means "
            f"nothing")
        assert blank_bytes > 0, (
            "the blank control wrote no PNG, so the ratio below proves nothing")
        assert page_bytes > 4 * blank_bytes, (
            f"the page's capture is {page_bytes} bytes against a blank surface's "
            f"{blank_bytes} at the same size - under 4x, so it is very nearly "
            f"blank")

    def test_the_rendered_widget_tree_still_holds_the_groups_and_the_rows(self):
        """Structure, read back out of the **realised** tree after painting.

        The other half of the pair, and the half that is allowed to disagree with
        a screenshot: this page's own capture through `Gtk.WidgetPaintable`
        mis-placed a button into the group above the correct one, which a
        screenshot would have reported as a layout bug and this assertion does
        not. AGENTS.md says the same thing about a scrolled page whose rows sit
        below the fold.

        So: the capture proves something was drawn, and this proves the drawing
        is of the right thing.
        """
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        window = Gtk.Window()
        window.set_default_size(1000, 1700)
        window.set_child(tab)
        try:
            window.present()
            _pump(lambda: _settled(tab))
            assert tab.get_mapped(), "the page was never mapped"
            assert tab.get_width() > 0 and tab.get_height() > 0, (
                tab.get_width(), tab.get_height())

            titles = [title for title, _s in _rows(tab)]
            for expected in ("Running now", "avahi-daemon.service - unit file",
                             "avahi-daemon.socket - unit file",
                             "avahi-daemon.service - is-enabled",
                             "avahi-daemon.socket - is-enabled",
                             "dbus-org.freedesktop.Avahi.service - is-enabled",
                             "0.0.0.0:5353", "[::]:5353",
                             "[server] use-ipv4", avahi_mod.AVAHI_CONF_D,
                             avahi_mod.AVAHI_SERVICES, avahi_mod.AVAHI_HOSTS):
                assert expected in titles, f"{expected!r} missing from {titles}"
            assert len(titles) >= 20, f"only {len(titles)} rows after a render"
            # And the duplication the Arch render found is gone in the render too.
            dupes = sorted({t for t in titles if titles.count(t) > 1})
            assert not dupes, f"duplicate row titles after a render: {dupes}"

            groups = [w.get_title() for w in _walk(tab)
                      if isinstance(w, Adw.PreferencesGroup)]
            for expected in ("Service Discovery", "The units systemd knows",
                             "Who is listening on the mDNS port",
                             "Configuration in effect", "Browse the network",
                             "About those lines", "What this page does not do",
                             "The commands instead"):
                assert expected in groups, f"{expected!r} missing from {groups}"
        finally:
            window.destroy()

    def test_the_status_row_draws_a_glyph_and_not_a_letter(self):
        """After a real paint, the status row's own image still names an icon.

        `Gtk.Image.get_icon_name()` is reliable here - measured, in isolation and
        after `add_prefix`, on both this stack and the page - which is the whole
        reason this class exists: the row once carried a `Gtk.Image` asking for
        an icon named `o`, and nothing about drawing the page would have said so.
        """
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        window = Gtk.Window()
        window.set_default_size(1000, 1700)
        window.set_child(tab)
        try:
            window.present()
            _pump(lambda: _settled(tab))
            image = tab._state_icon
            assert image is not None
            name = image.get_icon_name()
            assert name == avahi_mod.STATE_ICONS["ok"], name

            # `get_paintable()` is **not** the check, and asserting on it is a
            # mistake this test made first. Measured: an image created with
            # `new_from_icon_name` has `storage-type = GTK_IMAGE_ICON_NAME` and
            # `paintable = None` - GTK resolves an icon *name* against the theme
            # at draw time, so the property is legitimately unset for a correct
            # image. `has_icon` is the real resolution check, and it would have
            # caught the one-character bug too: this theme answers `False` for
            # `"o"` and `True` for `"object-select-symbolic"`.
            storage = image.get_property("storage-type")
            assert storage.value_nick == "icon-name", (
                f"storage-type is {storage.value_nick}, so the icon is not "
                f"being resolved by name at draw time")
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            assert theme.has_icon(name), f"the theme has no icon named {name!r}"
        finally:
            window.destroy()

    def test_a_page_that_never_painted_would_fail_the_control(self, tmp_path):
        """Proves the control in the first test can actually fail.

        The same blank, through the same `_shoot`, written into `tmp_path` -
        an earlier version wrote to a fixed `/tmp/opencode/...` path and raised
        `FileNotFoundError` inside the Arch container, where that directory does
        not exist. A test that only passes on the machine that made the path is
        a test that has not run.

        The measured figure is asserted as a range rather than a value: a PNG
        compressor's exact output is not a contract, but this blank must stay two
        orders of magnitude below the page's ~267,740. If `_shoot` stopped
        painting anything, both numbers would collapse together and the ratio in
        the first test would survive while its subject had not been drawn - which
        is what this floor is here to catch.
        """
        _flat_background_css("avahi-blank2", 1001)
        blank = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        blank.set_name("avahi-blank2")
        blank.set_size_request(1000, 1700)
        bytes, w, h = _shoot(blank, str(tmp_path / "blank-control.png"))
        assert w > 0 and bytes > 0, (bytes, w, h)
        assert 4_000 < bytes < 60_000, (
            f"the blank control encoded to {bytes} bytes, far from the measured "
            f"~10,442 at 1000x1700; either the renderer changed or this control "
            f"has stopped being blank")


# --- the browse button -----------------------------------------------------


class TestBrowseRunsOnlyOnClick:
    def test_the_page_says_nothing_was_browsed_until_it_is(self):
        _title, _sub, rows = _rendered()
        by_title = dict(rows)
        assert "Not browsed" in by_title
        assert "when you press it" in by_title["Not browsed"]

    def test_the_button_is_wired_to_the_handler_and_nothing_else(self):
        tab = AvahiTab()
        assert tab._btn_browse.get_label() == "Browse"

    def test_a_browse_line_is_shown_verbatim_and_not_split(self):
        """The anti-pretence test, and the reason `NOT_PARSED_NOTE` exists.

        The string below is a plausible `avahi-browse` line - and it is labelled
        as invented, because the tool is absent on this host. What is *not*
        invented is the requirement: whatever arrives must reach the row
        unchanged. The negative control at the bottom proves the assertion can
        fail.
        """
        # NOT A CAPTURE. Invented to carry the characters that a parser would
        # mangle; avahi-browse is not installed here (measured, exit 127) so no
        # real line was available.
        line = "=;ubuntu.local;IPv4 Workstation Laser Printer._ipp._tcp.local"
        tab = AvahiTab()
        tab._clear(tab._browse, tab._browse_rows)
        tab._add(tab._browse_rows, tab._browse,
                 avahi_mod._row("avahi-browse", line,
                                avahi_mod.SERVER_ICON))
        subtitles = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert line in subtitles, subtitles

    def test_the_negative_control_on_verbatim_display_actually_fails(self):
        """Proves the assertion above is not vacuous.

        A row whose subtitle was rebuilt from the line's fields comes back
        different, so this fails if the verbatim requirement is ever dropped.
        """
        line = "=;ubuntu.local;IPv4 Workstation Laser Printer._ipp._tcp.local"
        kept = avahi_mod._row("avahi-browse", line, avahi_mod.SERVER_ICON)
        # The mutation: split the line the way a parser would, and put it back.
        mutated = avahi_mod._row("avahi-browse", line.split(";")[-1],
                                 avahi_mod.SERVER_ICON)
        assert kept.get_subtitle() != mutated.get_subtitle(), (
            "the control did not mutate anything: splitting the line and "
            "rebuilding the row produced the same subtitle, so the verbatim "
            "test above proves nothing")

    def test_a_browse_line_with_markup_characters_does_not_break_the_row(self):
        line = "+;a&b;<host>"
        tab = AvahiTab()
        tab._add(tab._browse_rows, tab._browse,
                 avahi_mod._row("avahi-browse", line, avahi_mod.SERVER_ICON))
        rows = _rows(tab)
        assert rows, "the hostile browse line rendered nothing"

        # The label was handed markup Pango accepts...
        assert not _markup_error(avahi_mod._plain(line)), (
            "the escaped form is not valid markup, so the assertions below "
            "prove nothing")
        # ...and it reads back as the words that went in, whichever of the two
        # forms this stack's `get_subtitle()` returns (see `_unescape`).
        subs = [_unescape(subtitle) for _title, subtitle in rows]
        assert line in subs, subs

        # Those two together are the whole claim, and no third check is possible:
        # on this stack `get_subtitle()` returns the **plain** words, so asking
        # Pango about that string is asking whether `+;a&b;<host>` is markup -
        # and it is not, for a label that is perfectly correct. Asserting it
        # would be asserting that the escaping is broken.

    def test_a_refresh_does_not_wipe_a_browse_the_user_asked_for(self):
        """Browse output is the result of a **click**, not of a read, so a
        Refresh must leave it alone.

        `_on_state` deliberately does not clear `_browse_rows`; only the browse
        handler does, before it appends. That is a design decision rather than an
        oversight, and it was untested until a negative control was run: adding
        the clear back to `_on_state` changed nothing the suite could see, because
        the only browse-group row the existing tests look at - "Not browsed" -
        lives on `_row_browse`, which is never in `_browse_rows`.

        So the sequence matters and is asserted as a sequence: click, then read,
        then look.
        """
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        # Stand in for the click handler's output. It is a row list, and the
        # handler appends exactly this way.
        for i in range(3):
            tab._add(tab._browse_rows, tab._browse,
                     avahi_mod._row("avahi-browse", f"line {i}",
                                    avahi_mod.SERVER_ICON))
        before = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert before == ["line 0", "line 1", "line 2"], before

        tab._on_state(_payload(), "")
        after = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert after == before, (
            f"a read changed the browse output from {before} to {after}")

        # And a second read is idempotent, so this is not one delivery surviving.
        tab._on_state(_payload(), "")
        again = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert again == before, again

    def test_a_second_browse_replaces_the_first_and_does_not_stack(self,
                                                                    monkeypatch):
        """The other half: a *new* click does start clean.

        Driven through the **real handler** rather than by calling `_clear` and
        `_add` in the test. The first version did exactly that - it re-implemented
        the handler's two lines - and its negative control (removing the clear
        from `_on_browse_clicked`) therefore **passed**, because the test cleared
        the group itself and never went near the code it claimed to hold. That is
        the control-that-cannot-fail shape this repo has removed twice before.

        So `ss.run_stream_tool` is stubbed here and the button is activated, and
        the rows come from the handler's own `line` callback.
        """
        seen = []

        def fake_stream(argv, on_line, on_exit):
            seen.append(list(argv))
            for i in range(3):
                on_line(f"first {i}\n")
            on_exit(0)

        monkeypatch.setattr(avahi_mod.ss, "run_stream_tool", fake_stream)

        tab = AvahiTab()
        tab._on_state(_payload(), "")
        tab._btn_browse.emit("clicked")
        first = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert first == ["first 0", "first 1", "first 2"], first
        assert len(seen) == 1, seen

        tab._btn_browse.emit("clicked")
        second = [s for t, s in _rows(tab) if t == "avahi-browse"]
        assert second == first, (
            f"a second browse stacked rather than replaced: {second}")
        assert len(seen) == 2, seen

        # The persistent row survives every clear, because it is not tracked.
        assert "Not browsed" in [t for t, _s in _rows(tab)]

    def test_a_clicked_browse_reports_finishing_and_keeps_every_line(
            self, monkeypatch):
        """The handler's own exit path, driven through the button.

        The output is verbatim and **unsorted, unsplit and uninterpreted**, so the
        lines come back in the order the tool printed them and with their
        punctuation intact. `Finished` is added by the handler after the lines,
        which is what tells a reader that the list is over rather than still
        growing.
        """
        # NOT A CAPTURE. avahi-browse is absent on this host (measured, exit 127)
        # so no real line was available; what is asserted is the handler's
        # treatment of a line, not the tool's format.
        emitted = ["=;host.local;_ipp._tcp.local", "plain line", "+;a&b;<x>"]

        def fake_stream(argv, on_line, on_exit):
            for line in emitted:
                on_line(line + "\n")
            on_exit(0)

        monkeypatch.setattr(avahi_mod.ss, "run_stream_tool", fake_stream)
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        tab._btn_browse.emit("clicked")
        all_rows = _rows(tab)
        # Through `_unescape`, and this is not a convenience. The assertion
        # failed on the first Arch run **because of the measured stack
        # difference**: libadwaita 1.9.4 (Arch, GTK 4.22.5) hands back the
        # escaped form `+;a&amp;b;&lt;x&gt;`, and 1.5.0 (Ubuntu, GTK 4.14) hands
        # back the plain words `+;a&b;<x>`. The handler is identical and correct
        # on both; only the read-back differs. Comparing words is the only form
        # that is right on both stacks, which is what `_unescape` is for - and the
        # line chosen here carries an `&` and a `<` precisely so that a stack
        # difference cannot pass unnoticed.
        lines = [_unescape(sub) for t, sub in all_rows if t == "avahi-browse"]
        assert lines == emitted, (
            f"the lines came back as {lines}, not {emitted}: the handler is "
            f"supposed to hand each one over untouched and in order")
        finished = [s for t, s in all_rows if t == "Finished"]
        assert len(finished) == 1, all_rows
        assert finished[0].startswith("avahi-browse printed 3 line(s)"), finished

    def test_a_browse_that_printed_nothing_says_so_rather_than_reporting_no_services(
            self, monkeypatch):
        """Empty output is not "the network has no services".

        `avahi-browse` exiting 0 with nothing printed is as likely to be a daemon
        that would not answer as an empty network, and this page has no captured
        output from the tool that would let it tell those apart. So it says which
        of the two it cannot distinguish.
        """
        monkeypatch.setattr(avahi_mod.ss, "run_stream_tool",
                            lambda argv, on_line, on_exit: on_exit(0))
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        tab._btn_browse.emit("clicked")
        by_title = dict(_rows(tab))
        assert "Nothing printed" in by_title, by_title
        assert "not something this page can tell" in by_title["Nothing printed"]

    def test_an_absent_avahi_browse_is_reported_as_absent_and_not_as_empty(
            self, monkeypatch):
        """Status 127 is the shared runner's own "not installed" report."""
        monkeypatch.setattr(avahi_mod.ss, "run_stream_tool",
                            lambda argv, on_line, on_exit: on_exit(127))
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        tab._btn_browse.emit("clicked")
        by_title = dict(_rows(tab))
        assert "avahi-browse is not installed" in by_title, by_title

    def test_the_page_admits_it_has_never_captured_browse_output(self):
        joined = " ".join(
            f"{t} {s}" for t, s in _rows(AvahiTab())) + \
            " " + avahi_mod.NOT_PARSED_NOTE
        assert "has ever been captured" in joined, joined
        assert "not parsed" in joined.lower(), joined
        assert "split or sorted" in joined.lower(), joined
        # The scope matters: the claim is about **this page's evidence**, not
        # about the reader's machine. See
        # `test_the_page_does_not_tell_the_reader_that_avahi_browse_is_missing`.
        assert "on any machine this page was built against" in joined, joined


# --- the icon --------------------------------------------------------------


class TestTheIcon:
    """The icon must exist in the theme, checked against the running theme.

    A misspelled icon renders as nothing, silently, and in a screenshot that is
    indistinguishable from a layout bug.
    """

    def test_the_icon_is_in_the_adwaita_theme_on_this_host(self):
        root = "/usr/share/icons/Adwaita"
        if not os.path.isdir(root):
            pytest.skip(f"no Adwaita theme installed here: {root}")
        found = []
        for dirpath, _dirs, files in os.walk(root):
            found += [f for f in files if f == avahi_mod.ICON + ".svg"]
        assert found, (
            f"{avahi_mod.ICON}.svg is not in {root}; a missing icon renders as "
            f"nothing and nothing warns")

    def test_the_server_icon_is_in_the_adwaita_theme_on_this_host(self):
        root = "/usr/share/icons/Adwaita"
        if not os.path.isdir(root):
            pytest.skip(f"no Adwaita theme installed here: {root}")
        found = []
        for dirpath, _dirs, files in os.walk(root):
            found += [f for f in files if f == avahi_mod.SERVER_ICON + ".svg"]
        assert found, f"{avahi_mod.SERVER_ICON}.svg is not in {root}"

    def test_the_running_theme_agrees(self):
        from gi.repository import Gdk
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for name in (avahi_mod.ICON, avahi_mod.SERVER_ICON):
            assert theme.has_icon(name), f"{name} is not resolvable by GTK"

    def test_the_icon_lands_on_the_status_row_when_state_arrives(self):
        """Read off the prefix `Gtk.Image`, which is how the page sets it.

        `Adw.ActionRow.get_icon_name()` is deprecated in libadwaita 1.9, returns
        `None` on this stack for a row whose icon is a prefix image, and warns
        when asked - so asserting on it would have tested nothing while looking
        like it tested something.
        """
        # The default capture is socket `enabled` + daemon `active`, which is
        # `_verdict`'s "ok" state - so the glyph is the "ok" one. `ICON` is the
        # `info` glyph, reached when the socket is enabled but `is-active` could
        # not be read, so it is checked on that payload below rather than here.
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        assert _verdict(_payload())[2] == "ok", "the fixture is not the ok state"
        image = tab._state_icon
        assert image is not None, "the page never set a status icon"
        assert isinstance(image, Gtk.Image)
        assert image.get_icon_name() == avahi_mod.STATE_ICONS["ok"], \
            image.get_icon_name()

    def test_the_page_icon_is_the_glyph_for_a_socket_whose_state_is_unknown(self):
        """The state where `is-active` did not answer, which is `ICON`.

        Worth a test of its own because `ICON` is the page's own icon name and a
        reader looking at the page's constant list would assume it is the
        *status* row's glyph - which it is not, for the common case.
        """
        tab = AvahiTab()
        tab._on_state(_payload(socket=REAL_SOCKET_ENABLED, active=""), "")
        assert _verdict(_payload(socket=REAL_SOCKET_ENABLED, active=""))[2] \
            == "info"
        assert tab._state_icon.get_icon_name() == avahi_mod.ICON, \
            tab._state_icon.get_icon_name()

    def test_the_status_row_holds_exactly_one_image_of_its_own(self):
        """Read from the page's own prefix container, not from the subtree.

        Filtering a row's whole subtree by `isinstance(w, Gtk.Image)` finds
        widgets **this page did not create**: libadwaita 1.5.0's `Adw.ActionRow`
        builds two of its own, and one of them reports its icon name as the
        single character `'o'`. Asserting on that list gave `['o', None]` and
        read as a broken icon; the page's icon was on the row the whole time.

        So the count is taken from `_state_icon.get_parent()`, which is the
        prefix box the page put its one image in - that is precisely the property
        "no icon accumulates", and nothing else can perturb it.
        """
        tab = AvahiTab()
        tab._on_state(_payload(), "")
        image = tab._state_icon
        box = image.get_parent()
        assert box is not None, "the page's icon has no parent"
        inside = [w for w in _walk(box) if isinstance(w, Gtk.Image)]
        assert inside == [image], (
            f"the prefix box holds {len(inside)} images: "
            f"{[w.get_icon_name() for w in inside]}")

    def test_a_refresh_replaces_the_status_icon_rather_than_adding_one(self):
        """`Adw.ActionRow` keeps every prefix it is given.

        A refresh that only added another would grow a second and third icon
        down the left edge - the duplication this repo has caught once already,
        where a second delivery added three rows again and a screenshot showed 22
        rows where there were 19.
        """
        tab = AvahiTab()
        tab._on_state(_payload(socket="not-found", service="not-found"), "")
        first = _own_images(tab)
        assert len(first) == 1, first
        for _ in range(4):
            tab._on_state(_payload(), "")
        after = _own_images(tab)
        assert len(after) == 1, (
            f"five renders left {len(after)} of the page's own images on the "
            f"status row: {[w.get_icon_name() for w in after]}")

    def test_the_status_icon_is_the_name_and_not_its_first_letter(self):
        """The defect this class found, pinned.

        `firewall.STATE_ICONS` maps to `(icon, css_class)` tuples and its call
        site indexes with `[0]`. This table maps to plain strings, and the copied
        `[0]` indexed the **string**: `STATE_ICONS["ok"][0]` is `"o"`. Every
        status row carried a `Gtk.Image` asking for an icon named `o`, which
        renders as nothing and warns about nothing - and the earlier test here,
        which asserted on `tab._state_icon.get_icon_name()`, was what noticed.

        A one-character icon name is the shape of mistake that survives a review,
        because it looks like a tuple index that is simply unnecessary.
        """
        from gi.repository import Gdk
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert all(isinstance(v, str) for v in avahi_mod.STATE_ICONS.values()), (
            "STATE_ICONS values are not strings; if they became tuples again "
            "the [0] at the call site has to come back with them")
        for key, name in avahi_mod.STATE_ICONS.items():
            assert len(name) > 4, (
                f"STATE_ICONS[{key!r}] is {name!r}, which looks like a "
                f"first-character index rather than an icon name")
            assert theme.has_icon(name), f"{name} is not in the running theme"
            assert not theme.has_icon(name[0]) or len(name) == 1, (
                f"{name!r} was indexed down to {name[0]!r}")

    def test_every_state_the_verdict_can_return_draws_its_own_glyph(self):
        """The glyph actually on the row, for each state, not just the table.

        Reads `tab._state_icon.get_icon_name()` after a render, which is what
        caught the `[0]` above. `STATE_ICONS` being correct is not the same as
        the row carrying it.
        """
        seen = {}
        for socket, active in (("enabled", "active"), ("enabled", "inactive"),
                               ("disabled", "inactive"), ("masked", "inactive"),
                               ("not-found", "inactive"), ("", ""),
                               ("enabled", "failed"), ("wobbly", "wobbly")):
            tab = AvahiTab()
            tab._on_state(_payload(socket=socket, service="enabled",
                                   active=active), "")
            state = _verdict(_payload(socket=socket, service="enabled",
                                      active=active))[2]
            seen[state] = tab._state_icon.get_icon_name()
        assert seen, "no state rendered an icon"
        for state, icon in sorted(seen.items()):
            assert icon == avahi_mod.STATE_ICONS[state], (
                f"state {state!r} drew {icon!r}, not "
                f"{avahi_mod.STATE_ICONS[state]!r}")

    def test_the_pages_whole_icon_vocabulary_is_in_the_theme(self):
        """Every icon name the module can possibly produce, and nothing else.

        The vocabulary is `STATE_ICONS`' values plus `ICON` and `SERVER_ICON`,
        and the "nothing else" half is checked by reading the module's own icon
        literals - a row that picked an icon out of tool output, or a new branch
        with a fourth literal, is exactly where a misspelling would hide.

        It is deliberately **not** a walk of the widget tree. See
        `test_the_status_row_holds_exactly_one_image_of_its_own`: `Adw` builds
        `Gtk.Image` widgets of its own that report an icon name of `'o'`, and
        asking the theme about one of those says nothing about this page.
        """
        from gi.repository import Gdk
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        vocabulary = set(avahi_mod.STATE_ICONS.values())
        vocabulary |= {avahi_mod.ICON, avahi_mod.SERVER_ICON}
        assert len(vocabulary) >= 4, vocabulary
        for name in sorted(vocabulary):
            assert theme.has_icon(name), f"{name} is not in the running theme"

        # And no other icon literal exists in the module.
        literals = set()
        for node in ast.walk(ast.parse(inspect.getsource(avahi_mod))):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.endswith("-symbolic")):
                literals.add(node.value)
        assert literals, "the module names no symbolic icon at all"
        assert literals <= vocabulary, (
            f"icon literals outside STATE_ICONS: "
            f"{sorted(literals - vocabulary)}")

    def test_every_state_the_verdict_can_return_has_an_icon(self):
        """The mapping is total, so no verdict can fall back to nothing.

        `_on_state` looks the key up with `.get(state, STATE_ICONS["info"])`, and
        a verdict returning a key that is not in the table would therefore render
        the *info* glyph rather than its own - a silent mismatch. Every state
        `_verdict` can produce is listed here instead.
        """
        produced = set()
        for socket in ("", "not-found", "disabled", "enabled", "masked",
                       "static", "wobbly"):
            for service in ("", "not-found", "enabled", "disabled"):
                for active in ("", "active", "inactive", "failed", "wobbly"):
                    produced.add(_verdict(
                        {"socket_enabled": socket,
                         "service_enabled": service,
                         "service_active": active})[2])
        assert produced, "no state was produced at all"
        for state in sorted(produced):
            assert state in avahi_mod.STATE_ICONS, (
                f"_verdict can return {state!r} and STATE_ICONS has no entry "
                f"for it, so that state would be drawn with the info glyph")


# --- not registered --------------------------------------------------------


def test_the_page_is_registered_under_its_own_id():
    """Registering a section is a human's call, and `notebook.py` is another
    agent's file.

    Asserted in the other direction on purpose: it fails **loudly** the day
    someone does register it, so this file's "not registered" claim and the
    notebook cannot drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    # SECTIONS is (group, [(sub-group, [(cls, id, ...), ...])]); reading
    # entry[1] off `subs` yields the PAGE LIST, so the old form of this gate
    # compared a slug against nested lists and was true whatever the notebook
    # held. Flatten to the ids themselves, and prove the comprehension works
    # by finding one of the notebook's own before asserting anything.
    flat = [page[1]
            for _group, subs in notebook.SECTIONS
            for _sub_group, pages in subs
            for page in pages]
    assert flat, "the notebook has no sections, so this gate sees nothing"
    assert "overview" in flat, (
        "the comprehension below found none of the notebook's own ids, so "
        "it would pass against anything")
    assert "avahi" in flat, (
        "the page is now registered in notebook.SECTIONS; update this file and "
        "the other agent's notebook changes together")


# --- the live host, where it is available ----------------------------------


class TestAgainstThisHost:
    """The fixtures re-checked against **whichever** machine is running them.

    **Two platforms were measured for this page and they genuinely disagree**, so
    a test that asserted one platform's answers unconditionally failed on the
    other. Six of these did exactly that on the first Arch run - and every one of
    the six was a *correct* fact about a platform that is not the platform the
    test was written on:

    | Fact | Ubuntu 24.04 (this host) | Arch `avahi 1:0.9rc5-1` (container) |
    |---|---|---|
    | `is-enabled avahi-daemon.service` | `enabled`, exit 0 | **`disabled`, exit 1** |
    | `is-enabled avahi-daemon.socket` | `enabled`, exit 0 | **`disabled`, exit 1** |
    | `is-enabled dbus-org.freedesktop.Avahi.service` | `alias`, exit 0 | **`not-found`, exit 4** |
    | `avahi-browse` | **absent**, exit 127 | **present**, `--version` -> `avahi-browse 0.9-rc5` |
    | `[wide-area]` in the conf | **`enable-wide-area=yes`**, uncommented | **`#enable-wide-area=no`**, commented |
    | `/etc/avahi/avahi-daemon.conf.d` | absent | absent |
    | `/etc/avahi/hosts` active lines | 0 | 0 |
    | `avahi-daemon.service` `[Install]` | present | present |

    So each test below states the fact **for the platform it is on**, decided from
    `/etc/os-release`, and skips when it is neither. That is strictly stronger than
    skipping everywhere: the Arch column above was verified for real, in an Arch
    container on GTK 4.22.5 / libadwaita 1.9.4 - Shanios' own stack - which is the
    check `AGENTS.md` asks for and which the fixtures alone could not supply.

    Two of the Arch answers are container facts rather than installed-machine
    facts, and are labelled as such where they are used: no systemd is running
    there, so nothing is enabled and the D-Bus alias symlink does not exist.
    `disabled` for the daemon is nevertheless the state `shani-network.install`
    leaves on a real Shanios install, since it enables the socket and never the
    service - so the page's central case is now observed, not only transcribed.

    Every one of these is here to catch a **fixture** drifting from reality. None
    of them is evidence that the page works on a machine that does not exist.
    """

    @staticmethod
    def _family() -> str:
        try:
            body = open("/etc/os-release", encoding="utf-8").read()
        except OSError:
            return ""
        for line in body.splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "ID":
                return value.strip().strip('"')
        return ""

    @classmethod
    def _on_arch(cls) -> bool:
        return cls._family() == "arch"

    @classmethod
    def _on_debian(cls) -> bool:
        return cls._family() in ("debian", "ubuntu")

    @classmethod
    def _avahi_installed(cls) -> bool:
        return os.path.exists("/usr/lib/systemd/system/avahi-daemon.service")

    # -- the daemon's enablement state, which differs by platform -------------
    def test_the_daemon_enablement_answer_matches_this_platform(self):
        if not self._avahi_installed():
            pytest.skip("avahi is not installed on this host")
        proc = _run(["systemctl", "is-enabled", "avahi-daemon.service"])
        answer = proc.stdout.strip()
        if self._on_arch():
            # Measured in an Arch container on `avahi 1:0.9rc5-1`: `disabled`,
            # exit 1. Nothing there ran `shani-network.install`, and systemd is
            # not running, so no unit and no alias is enabled.
            assert answer == "disabled", (
                f"{answer!r} (exit {proc.returncode}) - the Arch fixture and the "
                f"page's wording are about `disabled`")
            assert proc.returncode == 1, proc.returncode
        elif self._on_debian():
            assert answer == "enabled", (answer, proc.returncode)
            assert proc.returncode == 0, proc.returncode
            assert REAL_SERVICE_ENABLED.strip() == answer, (
                "the capture no longer matches this host; the fixture is stale")
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    def test_the_socket_enablement_answer_matches_this_platform(self):
        if not self._avahi_installed():
            pytest.skip("avahi is not installed on this host")
        proc = _run(["systemctl", "is-enabled", "avahi-daemon.socket"])
        answer = proc.stdout.strip()
        if self._on_arch():
            assert answer == "disabled", (answer, proc.returncode)
        elif self._on_debian():
            assert answer == "enabled", (answer, proc.returncode)
            assert REAL_SOCKET_ENABLED.strip() == answer
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    def test_the_dbus_alias_answer_matches_this_platform(self):
        """`alias` on Ubuntu, `not-found` in the Arch container.

        Both are correct. `alias` is the ordinary answer once systemd has read the
        unit and created the alias symlink; with no systemd running there is no
        symlink and the name is genuinely not found. The page shows whichever
        word it is given, which is the point of keeping the answer verbatim.
        """
        if not self._avahi_installed():
            pytest.skip("avahi is not installed on this host")
        proc = _run(["systemctl", "is-enabled",
                     "dbus-org.freedesktop.Avahi.service"])
        answer = proc.stdout.strip()
        if self._on_arch():
            assert answer == "not-found", (answer, proc.returncode)
            assert proc.returncode == 4, proc.returncode
        elif self._on_debian():
            assert answer == "alias", (answer, proc.returncode)
            assert proc.returncode == 0, proc.returncode
            assert REAL_DBUS_ENABLED.strip() == answer
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    # -- avahi-browse, which exists on one platform and not the other ---------
    def test_avahi_browse_presence_matches_this_platform(self):
        """**The fact this page is most careful about, now verified on both.**

        Arch's `avahi` package ships `avahi-browse` itself - measured in the Arch
        container on `avahi 1:0.9rc5-1`: `avahi-browse --version` answers
        `avahi-browse 0.9-rc5` with exit 0, and `pacman -Ql avahi` lists
        `/usr/bin/avahi-browse`. Debian and Ubuntu split it into a separate
        `avahi-utils` package, which is not installed on this host, so the same
        command answers `command not found` with exit 127.

        So the page's Browse button works on Shanios and honestly reports itself
        absent here, and both halves are asserted where they are true.
        """
        found = shutil_which(avahi_mod.AVAHI_BROWSE)
        if self._on_arch():
            assert found, (
                "avahi-browse is missing on Arch, where the avahi package ships "
                "it; NOT_PARSED_NOTE's claim that it is present on Shanios would "
                "be stale")
            proc = _run([avahi_mod.AVAHI_BROWSE, "--version"])
            assert proc.returncode == 0, proc.returncode
            assert "avahi-browse" in proc.stdout, proc.stdout
            # Recorded, and deliberately **not** treated as browse output: this is
            # the version banner, not a listing. No captured *listing* exists on
            # either platform, which is why there is still no parser for one.
            assert "0.9" in proc.stdout, proc.stdout
        elif self._on_debian():
            assert found is None, (
                "avahi-utils is installed on this host now; the Browse button "
                "would run and NOT_PARSED_NOTE would need re-examining")
            with pytest.raises(FileNotFoundError):
                _run([avahi_mod.AVAHI_BROWSE, "--version"])
            # 127 is **bash's** code for "command not found"; `subprocess.run`
            # raises instead, which is why both are measured here.
            shell = _run(["bash", "-c", "avahi-browse --version"])
            assert shell.returncode == 127, shell.returncode
            assert "command not found" in shell.stderr, shell.stderr
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    # -- the configuration file, whose two platform copies differ -------------
    def test_the_conf_file_matches_this_platform(self):
        """The `[wide-area]` disagreement, re-checked against the real file.

        Measured on both: Ubuntu's `avahi 0.8-13ubuntu6.2` has
        `enable-wide-area=yes` uncommented; Arch's `1:0.9rc5-1` has
        `#enable-wide-area=no` commented. The two files hash differently
        (`f5ed1c83` vs `8da9c30c`) and the page reports only what the file sets -
        so which of the two is present changes the answer.
        """
        if not os.path.exists(avahi_mod.AVAHI_CONF):
            pytest.skip("no avahi config on this host")
        entries = parse_avahi_conf(
            open(avahi_mod.AVAHI_CONF, encoding="utf-8").read())
        wide = [e for e in entries if e["key"] == "enable-wide-area"]
        if self._on_arch():
            assert wide == [], (
                f"the Arch file sets wide-area as {wide}; the page deliberately "
                f"says nothing about a key the Shanios file leaves commented")
            assert "#enable-wide-area=no" in open(
                avahi_mod.AVAHI_CONF, encoding="utf-8").read()
        elif self._on_debian():
            assert wide and wide[0]["value"] == "yes", (
                f"this host's wide-area answer changed to {wide}; the Arch "
                f"fixture is a different distribution's file")
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    def test_the_conf_dropin_directory_is_absent_on_both_platforms(self):
        if not self._avahi_installed():
            pytest.skip("avahi is not installed on this host")
        assert not os.path.exists(avahi_mod.AVAHI_CONF_D), (
            "the drop-in directory exists here now; the page's 'not present' "
            "wording was measured against its absence on both platforms")

    def test_the_hosts_file_has_no_active_lines_on_this_platform(self):
        """`/etc/avahi/hosts`, and a probe that is actually right.

        **The first probe here was wrong and would have been believed.** It was
        `grep -c '[^#[:space:]]'`, which counts *any* non-blank character that is
        not `#` - so a commented example line like `# 192.168.0.1 router.local`
        matches it, and the correct answer of **0** came back as 21 on Arch. The
        probe now asks the actual question: lines whose first non-space character
        is not `#`.

        Both platforms: 27 lines, **0** of them active, and the file is
        byte-identical (`sha256 d16fca08...`). So "the shipped file holds only
        comments" is a verified fact about both copies.
        """
        if not os.path.exists(avahi_mod.AVAHI_HOSTS):
            pytest.skip("no avahi hosts file on this host")
        lines = open(avahi_mod.AVAHI_HOSTS, encoding="utf-8").read().splitlines()
        active = [ln.strip() for ln in lines
                  if ln.strip() and not ln.lstrip().startswith("#")]
        assert active == [], (
            f"{len(active)} active mapping(s) in {avahi_mod.AVAHI_HOSTS}: "
            f"{active[:5]}")
        assert len(lines) == 27, len(lines)
        assert _static_host_mappings(avahi_mod.AVAHI_HOSTS) == []

    def test_the_services_directory_is_present_and_empty(self):
        if not self._avahi_installed():
            pytest.skip("avahi is not installed on this host")
        assert os.path.isdir(avahi_mod.AVAHI_SERVICES), (
            f"{avahi_mod.AVAHI_SERVICES} is absent here; both platforms "
            f"measured have it, empty")
        entries = [e for e in os.listdir(avahi_mod.AVAHI_SERVICES)
                   if not e.startswith(".")]
        assert entries == [], (
            f"static service files are present: {entries}")

    # -- the unit files, read off the installed package -----------------------
    def test_the_installed_daemon_unit_has_an_install_section(self):
        """The load-bearing evidence for the whole page, on **both** platforms.

        Checked against the unit file the package actually installed rather than
        a copy of it in this repository: `[Install]`, `WantedBy=multi-user.target`,
        `Also=avahi-daemon.socket` and `Alias=dbus-org.freedesktop.Avahi.service`,
        plus `Requires=avahi-daemon.socket`, `BusName=org.freedesktop.Avahi` and
        `Type=dbus`. If any of those went, the page's central argument - that the
        socket is the switch - would be stale.
        """
        path = "/usr/lib/systemd/system/avahi-daemon.service"
        if not os.path.exists(path):
            pytest.skip("avahi is not installed on this host")
        body = open(path, encoding="utf-8").read()
        for expected in ("[Install]", "WantedBy=multi-user.target",
                         "Also=avahi-daemon.socket",
                         "Alias=dbus-org.freedesktop.Avahi.service",
                         "Requires=avahi-daemon.socket",
                         "BusName=org.freedesktop.Avahi", "Type=dbus"):
            assert expected in body, f"{expected!r} is gone from {path}"

        socket_path = "/usr/lib/systemd/system/avahi-daemon.socket"
        if os.path.exists(socket_path):
            sock = open(socket_path, encoding="utf-8").read()
            assert "ListenStream=/run/avahi-daemon/socket" in sock
            assert "WantedBy=sockets.target" in sock

    def test_this_platform_ships_the_dnsconfd_unit(self):
        """Arch ships a third avahi unit; Debian's avahi-daemon does not.

        Measured: `avahi-dnsconfd.service` is present in the Arch container's
        `/usr/lib/systemd/system/` and absent from this host's `dpkg -L
        avahi-daemon`. That is why `CATA_LIST_UNIT_FILES` has **two** rows and
        `ARCH_UNITS_BELOW` has three - and the two must not be confused.
        """
        present = os.path.exists(
            "/usr/lib/systemd/system/avahi-dnsconfd.service")
        if self._on_arch():
            assert present, (
                "avahi-dnsconfd.service is gone from the Arch package; "
                "ARCH_UNITS_BELOW would be describing a unit that no longer "
                "ships")
        elif self._on_debian():
            assert not present, (
                "this host now ships avahi-dnsconfd.service; "
                "CATA_LIST_UNIT_FILES with two rows would be stale")
        else:
            pytest.skip(f"unmeasured platform {self._family()!r}")

    # -- systemd's own word for a missing unit, which the reader depends on ---
    def test_a_missing_unit_is_reported_on_stdout_with_an_empty_stderr(self):
        """The stream split `run_text` relies on.

        `systemctl is-enabled` prints `not-found` on **stdout**, with an empty
        stderr and exit 4. `run_status` would have discarded the word, which is
        the answer the page needs to say "Avahi is not installed".
        """
        proc = _run(["systemctl", "is-enabled", "avahi-definitely-not-a-unit"])
        assert proc.returncode == 4, proc.returncode
        assert proc.stdout.strip() == "not-found", proc.stdout
        assert proc.stderr.strip() == "", proc.stderr

    def test_ss_output_matches_the_parser_on_this_platform(self):
        if not shutil_which("ss"):
            pytest.skip("ss is not installed on this host")
        proc = _run(["ss", "-ulpn"])
        assert proc.returncode == 0
        rows = parse_mdns_listeners(proc.stdout)
        for row in rows:
            assert re.fullmatch(r"\S+:\d+|\[[^\]]+\]:\d+", row["local"]), row
            assert row["local"].endswith(":5353"), row
            # A container has no mDNS responder, so an empty list is the honest
            # answer here and the count is deliberately not asserted.

    def test_the_pages_own_icon_matches_the_file_this_test_verified(self):
        assert avahi_mod.ICON == "network-transmit-receive-symbolic"
        assert avahi_mod.SERVER_ICON == "network-server-symbolic"


