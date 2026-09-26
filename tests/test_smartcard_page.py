"""The smartcard page: every state it can be in, and what it refuses to do.

The data layer is already tested in test_system_status.py, so nothing here
re-tests it. What is tested is the page's own judgement: which rows it renders
for which shape of the data, that a certificate subject is escaped rather than
taken as markup, that a file with a line it could not read is shown read-only,
and the two hard gates - no login-stack path and no PIN flag may appear in this
module at all.
"""

import ast
import time

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import smartcard as sc  # noqa: E402


def spin(cond, timeout=5.0):
    """Iterate the main loop until cond() holds - the shape test_tabs and
    test_system_status already use for every async answer."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


# --- fixtures --------------------------------------------------------------

# What the data layer reports on a machine that has the module and the shipped
# comment-only mapping. Every value here is a shape the data layer actually
# returns (see test_system_status.py), not one invented for the page.
PKCS11_STATE = {
    "installed": True,
    "conf_exists": True,
    "mappers": {
        "mapper subject": {"module": "internal",
                           "mapfile": "file:///etc/pam_pkcs11/subject_mapping"},
        "mapper openssh": {"module": "openssh",
                           "mapfile": "pubkey:file:///home/$USER/.ssh/authorized_keys"},
    },
    "provider": "/usr/lib/opensc-pkcs11.so",
    "problems": [],
}

MAPPED = {"exists": True,
          "entries": [{"subject": "CN=Shani Admin,O=SHANI,C=LOCAL",
                       "login": "shani", "lineno": 1},
                      {"subject": "CN=Shani Ops,O=SHANI,C=LOCAL",
                       "login": "ops", "lineno": 3}],
          "problems": [],
          "path": "/etc/pam_pkcs11/subject_mapping"}

# `make install` writes comments and nothing else, so zero entries is the
# normal first-run state and not a fault.
EMPTY = {"exists": True, "entries": [], "problems": [],
         "path": "/etc/pam_pkcs11/subject_mapping"}

MISSING = {"exists": False, "entries": [], "problems": [],
           "path": "/etc/pam_pkcs11/subject_mapping"}

UNREADABLE = {"exists": True, "entries": [],
              "problems": [{"lineno": 2, "raw": "jdoe",
                            "why": "there is no '->' in it"}],
              "path": "/etc/pam_pkcs11/subject_mapping"}

# hardware_auth_status() rows, one per state it can report.
AUTH_ROWS = [
    {"title": "Smartcard (PIV) login", "module": "pam_pkcs11.so", "state": "ok",
     "detail": "gdm-smartcard — pam_pkcs11.so present"},
    {"title": "Smartcard (PIV) unlock", "module": "pam_pkcs11.so", "state": "unavailable",
     "detail": "kde-smartcard needs pam_pkcs11.so, which this image does not ship"},
    {"title": "Fingerprint login", "module": "pam_fprintd.so", "state": "ok",
     "detail": "pam_fprintd.so — offered by gdm-fingerprint"},
]


class Fake:
    """Every call this page makes, recorded so a test can assert on it."""

    def __init__(self):
        self.pkcs11 = dict(PKCS11_STATE)
        self.mappings = dict(EMPTY)
        self.auth = list(AUTH_ROWS)
        self.readers = ([], "")        # the (readers, error) pair pcsc_readers reports
        self.writes = []            # ("set"|"remove", subject, login)
        self.write_result = ("", "Saved /etc/pam_pkcs11/subject_mapping")


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(ss, "pam_pkcs11_state", lambda: dict(f.pkcs11))
    monkeypatch.setattr(ss, "subject_mappings", lambda: dict(f.mappings))
    monkeypatch.setattr(ss, "hardware_auth_status", lambda: list(f.auth))
    monkeypatch.setattr(ss, "pcsc_readers", lambda done: done(*f.readers))

    def set_mapping(subject, login, *, done):
        f.writes.append(("set", subject, login))
        done(*f.write_result)

    def remove_mapping(subject, *, done):
        f.writes.append(("remove", subject, ""))
        done(*f.write_result)

    monkeypatch.setattr(ss, "set_mapping", set_mapping)
    monkeypatch.setattr(ss, "remove_mapping", remove_mapping)
    return f


class _Clip:
    """The clipboard, so a Copy button can be tested without a display."""

    def __init__(self):
        self.copied = []

    def set(self, text):
        self.copied.append(text)


def build(fake):
    """A constructed page, with its toasts and its clipboard captured."""
    page = sc.SmartcardTab()
    page.toasted = []
    page.clip = _Clip()
    page.get_clipboard = lambda: page.clip
    page._toast = page.toasted.append
    return page


@pytest.fixture
def page(fake):
    return build(fake)


# --- helpers ---------------------------------------------------------------

def walk(widget):
    out = []
    stack = [widget]
    while stack:
        w = stack.pop(0)
        out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def rows(widget):
    return [w for w in walk(widget) if isinstance(w, Adw.ActionRow)]


def texts(page):
    return [(r.get_title(), r.get_subtitle()) for r in rows(page)]


def buttons(page):
    return [b.get_label() for b in walk(page)
            if isinstance(b, Gtk.Button) and b.get_label()]


def groups(page):
    return [w for w in walk(page) if isinstance(w, Adw.PreferencesGroup)]


def group_titled(page, needle):
    for w in groups(page):
        if needle in (w.get_title() or ""):
            return w
    raise AssertionError(f"no preferences group titled like {needle!r}; "
                         f"there is {[g.get_title() for g in groups(page)]}")


def entry_rows(dialog):
    """The entry rows a dialog asks with. An Adw.AlertDialog keeps its content
    out of the widget tree until it is presented, so the walk starts at the
    extra child it was given."""
    return [w for w in walk(dialog.get_extra_child()) if isinstance(w, Adw.EntryRow)]


def labelled(widget, label):
    for b in walk(widget):
        if isinstance(b, Gtk.Button) and b.get_label() == label:
            return b
    raise AssertionError(f"no button labelled {label!r}")


# --- construction ----------------------------------------------------------

def test_the_page_constructs_like_every_other_tab():
    from shani_cassini.state import AppState
    from shani_cassini.auth import AuthManager

    state, auth = AppState(), AuthManager()
    tab = sc.SmartcardTab(state=state, auth_manager=auth)
    assert isinstance(tab, Gtk.Box)
    assert tab.get_orientation() == Gtk.Orientation.VERTICAL
    assert tab._state is state
    assert tab._auth_manager is auth


def test_the_content_lives_under_a_toast_overlay(fake):
    tab = sc.SmartcardTab()
    overlays = [w for w in walk(tab) if isinstance(w, Adw.ToastOverlay)]
    assert len(overlays) == 1
    assert overlays[0].get_child() is not None


# --- 1. status -------------------------------------------------------------

def test_status_rows_reuse_the_data_layers_wording_verbatim(page):
    """Every smartcard row of hardware_auth_status(), word for word."""
    titles = {r["title"] for r in AUTH_ROWS if r["module"] == "pam_pkcs11.so"}
    got = [(t, s) for t, s in texts(page) if t in titles]
    assert got == [(r["title"], r["detail"]) for r in AUTH_ROWS
                   if r["module"] == "pam_pkcs11.so"], \
        f"the smartcard rows were not rendered as the data layer wrote them: {got}"


def test_status_shows_only_the_smartcard_rows(page):
    """A fingerprint or security-key row belongs to its own page."""
    titles = [t for t, _ in texts(page)]
    assert "Fingerprint login" not in titles
    assert "Card readers" in titles


def test_card_readers_reports_the_readers_pcsc_scan_found(fake):
    fake.readers = ([{"nr": 0, "text": "Yubico YubiKey OTP+FIDO+CCID 00 00 "},
                     {"nr": 1, "text": "Feitian ePass FIDO2 3b 65 "}], "")
    row = [r for r in rows(build(fake)) if r.get_title() == "Card readers"][0]
    assert "Yubico YubiKey" in row.get_subtitle()
    assert "Feitian ePass" in row.get_subtitle()


def test_card_readers_says_so_when_nothing_is_attached(fake):
    """An empty list means pcsc_scan answered and found nothing, which is not
    the same as the daemon not answering."""
    fake.readers = ([], "")
    row = [r for r in rows(build(fake)) if r.get_title() == "Card readers"][0]
    assert row.get_subtitle() == "No reader found"


def test_card_readers_reports_the_error_rather_than_no_reader(fake):
    """pcsc_readers hands back None for a daemon that did not answer."""
    fake.readers = (None, "pcsc_scan exited 127")
    row = [r for r in rows(build(fake)) if r.get_title() == "Card readers"][0]
    assert row.get_subtitle() == "pcsc_scan exited 127"


def test_the_page_does_not_block_on_the_readers(fake, monkeypatch):
    """pcsc_scan is a subprocess. The page must show it is still asking and
    come back to it later, not wait for it."""
    asked = []
    monkeypatch.setattr(ss, "pcsc_readers", lambda done: asked.append(done))
    page = sc.SmartcardTab()
    assert page._row_readers.get_subtitle() == "Looking…", \
        "the page did not show that it was still asking pcsc_scan"
    assert len(asked) == 1
    asked[0]([{"nr": 0, "text": "Yubico YubiKey 00 "}], "")
    assert "Yubico YubiKey" in page._row_readers.get_subtitle()


# --- 2. how a card is matched ---------------------------------------------

def test_the_matching_group_shows_the_real_mapper_and_provider(page):
    got = dict(texts(page))
    assert "internal" in got["Subject mapper"]
    assert "file:///etc/pam_pkcs11/subject_mapping" in got["Subject mapper"]
    assert got["PKCS#11 provider"] == "/usr/lib/opensc-pkcs11.so"
    assert "openssh" in got["Other mappers"]


def test_the_matching_group_offers_no_mapper_switch(page):
    """A mapper switch is the one edit that silently disables every card, so
    the group has to be free of controls and to say why."""
    g = group_titled(page, "How a card is matched")
    found = [w for w in walk(g) if isinstance(w, (Gtk.Button, Gtk.Switch))]
    assert found == [], f"the matching group offers controls: {found}"
    why = (g.get_description() or "").lower()
    assert "switch" in why and "mapper" in why, \
        f"the group does not say why it is read-only: {g.get_description()!r}"


def test_the_matching_group_names_every_problem(fake):
    fake.pkcs11 = dict(PKCS11_STATE,
                       problems=["/etc/pam_pkcs11/pam_pkcs11.conf is missing - the module "
                                 "has no configuration to use"])
    body = " ".join(f"{t} {s}" for t, s in texts(build(fake)))
    assert "has no configuration to use" in body, \
        f"a problem from pam_pkcs11_state was not shown: {body}"


# --- 3. the mappings -------------------------------------------------------

def test_an_empty_template_is_not_an_error_state(page):
    """`make install` writes a comment-only file: the normal first-run state,
    which must not read as a fault."""
    assert not page.toasted
    body = " ".join(f"{t} {s}" for t, s in texts(page))
    assert "None" in body, f"the empty mapping file said nothing at all: {body}"
    for bad in ("could not be read", "not present", "refused", "error"):
        assert bad not in body, \
            f"an empty mapping file was rendered as {bad!r}: {body}"
    assert not any(t.startswith("CN=") for t, _ in texts(page))


def test_one_row_per_mapping_titles_the_subject_and_subtitles_the_account(fake):
    fake.mappings = MAPPED
    got = [(t, s) for t, s in texts(build(fake)) if t.startswith("CN=")]
    assert got == [("CN=Shani Admin,O=SHANI,C=LOCAL", "shani"),
                   ("CN=Shani Ops,O=SHANI,C=LOCAL", "ops")]


def test_a_subject_full_of_markup_is_escaped_not_rendered(fake):
    """These strings come out of a root-owned file. A subject carrying markup
    must reach the label as text, never as tags."""
    subject = 'CN="Ops <b>team</b> & co",O=SHANI'
    fake.mappings = {"exists": True,
                     "entries": [{"subject": subject, "login": "ops<1>", "lineno": 1}],
                     "problems": [], "path": MAPPED["path"]}
    row = [r for r in rows(build(fake)) if "Ops" in (r.get_title() or "")][0]
    assert row.get_title() == GLib.markup_escape_text(subject), \
        f"the subject was not escaped: {row.get_title()!r}"
    assert "<b>" not in row.get_title()
    # An AdwActionRow hands the subtitle back unescaped, and a raw "<1>" is not
    # markup at all: libadwaita fails to parse it, logs a Gtk-WARNING and leaves
    # the subtitle empty. So the plain text coming back is the proof that the
    # escaped form is what the label was given.
    assert row.get_subtitle() == "ops<1>", \
        f"the account was not escaped into the label: {row.get_subtitle()!r}"


def test_every_mapping_offers_edit_and_remove(fake):
    fake.mappings = MAPPED
    g = group_titled(build(fake), "Certificate")
    assert buttons(g).count("Edit…") == 2
    assert buttons(g).count("Remove…") == 2
    assert "Add a mapping…" in buttons(g)


def test_a_file_with_a_line_it_cannot_read_is_shown_read_only(fake):
    fake.mappings = UNREADABLE
    g = group_titled(build(fake), "Certificate")
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "3" in body, f"the bad line's number was not shown: {body}"
    assert "jdoe" in body or "no '->'" in body, f"the bad line was not shown: {body}"
    assert buttons(g) == [], \
        f"a file Cassini cannot read still offered editing: {buttons(g)}"


def test_a_missing_file_names_the_package_that_ships_it(fake):
    fake.mappings = MISSING
    page = build(fake)
    body = " ".join(f"{t} {s}" for t, s in texts(page))
    assert "shani-peripherals" in body, \
        f"a missing file did not say who ships it: {body}"
    assert "Add a mapping…" not in buttons(page)


def test_editing_a_mapping_writes_through_the_data_layer(fake):
    fake.mappings = MAPPED
    page = build(fake)
    d = page._edit_dialog("CN=Shani Ops,O=SHANI,C=LOCAL", "ops")
    entry, = entry_rows(d)
    entry.set_text("opsadmin")
    d.emit("response", "save")
    assert fake.writes == [("set", "CN=Shani Ops,O=SHANI,C=LOCAL", "opsadmin")], \
        f"the edit did not reach the data layer: {fake.writes}"
    assert page.toasted == ["Saved /etc/pam_pkcs11/subject_mapping"]


def test_a_failed_set_mapping_surfaces_the_message_it_returned(fake):
    """The refusal is the data layer's own words; paraphrasing it would send
    the user off to fix the wrong thing."""
    refusal = ("/etc/pam_pkcs11/subject_mapping has no entry for this certificate, "
               "and Cassini cannot add a line to it - add it in a terminal, then "
               "set its login name here")
    fake.mappings = MAPPED
    fake.write_result = (refusal, "")
    page = build(fake)
    d = page._add_dialog()
    subject, login = entry_rows(d)
    subject.set_text("CN=Shani Ops,O=SHANI,C=LOCAL")
    login.set_text("ops")
    d.emit("response", "save")
    assert page.toasted == [refusal], \
        f"the refusal was not surfaced as the data layer wrote it: {page.toasted}"


def test_a_failed_removal_surfaces_the_message_it_returned(fake):
    refusal = "/etc/pam_pkcs11/subject_mapping has no entry for that certificate"
    fake.mappings = MAPPED
    fake.write_result = (refusal, "")
    page = build(fake)
    page._remove_dialog("CN=Shani Ops,O=SHANI,C=LOCAL").emit("response", "remove")
    assert fake.writes == [("remove", "CN=Shani Ops,O=SHANI,C=LOCAL", "")]
    assert page.toasted == [refusal], \
        f"the refusal was not surfaced as the data layer wrote it: {page.toasted}"


def test_removing_asks_first(fake):
    fake.mappings = MAPPED
    page = build(fake)
    d = page._remove_dialog("CN=Shani Ops,O=SHANI,C=LOCAL")
    assert d.get_response_appearance("remove") == Adw.ResponseAppearance.DESTRUCTIVE
    assert d.get_default_response() == "cancel"
    assert fake.writes == [], "the mapping went before anybody confirmed it"


@pytest.mark.parametrize("subject,login", [
    ("", "ops"),
    ("   ", "ops"),
    ("CN=Shani Ops", ""),
    ("CN=A -> B", "ops"),          # a '->' inside the subject
    ("CN=Shani Ops", "a -> b"),    # a '->' inside the login
])
def test_set_mapping_is_never_called_with_something_it_refuses(fake, subject, login):
    """The dialog's own check, re-checked at the call: the data layer would
    refuse these anyway, and a refusal is not a save."""
    fake.mappings = MAPPED
    page = build(fake)
    d = page._add_dialog()
    s, l = entry_rows(d)
    s.set_text(subject)
    l.set_text(login)
    d.emit("response", "save")
    assert fake.writes == [], \
        f"set_mapping was called with a pair it refuses: {fake.writes}"


def test_save_stays_disabled_until_the_pair_is_writable(fake):
    d = build(fake)._add_dialog()
    subject, login = entry_rows(d)
    for text in ("", "  ", " CN=Shani", "CN=Shani ", "CN=Shani -> x"):
        subject.set_text(text)
        login.set_text("ops")
        assert d.get_response_enabled("save") is False, \
            f"Save was enabled for subject {text!r}"
    subject.set_text("CN=Shani")
    for text in ("", "   ", "ops -> root"):
        login.set_text(text)
        assert d.get_response_enabled("save") is False, \
            f"Save was enabled for login {text!r}"
    login.set_text("ops")
    assert d.get_response_enabled("save") is True


# --- 4. from a terminal ---------------------------------------------------

def test_the_two_commands_are_shown_with_a_copy_button(page):
    g = group_titled(page, "From a Terminal")
    assert buttons(g) == ["Copy", "Copy"]
    body = " ".join(f"{t} {s}" for t, s in texts(g))
    assert "pkcs15-tool" in body
    assert "pkcs11-tool" in body, \
        f"the reason the app hands the command over is missing: {body}"


def test_a_command_is_copied_verbatim(page):
    shown = [t for t, _ in texts(group_titled(page, "From a Terminal"))]
    copy = labelled(group_titled(page, "From a Terminal"), "Copy")
    copy.emit("clicked")
    assert page.clip.copied == [shown[0]], \
        f"what landed on the clipboard is not the command shown: {page.clip.copied}"


# --- the two immutable gates ----------------------------------------------

def _module_constants():
    """Every string literal in the page module, from its own AST."""
    with open(sc.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_no_login_stack_path_appears_in_this_module():
    """A /etc/pam.d file is the login stack: root-owned, and it decides who
    gets in. This page has no business naming one."""
    bad = sorted({c for c in _module_constants() if "/etc/pam.d" in c})
    assert bad == [], \
        f"this page names login-stack paths, which must never be writable from here: {bad}"


def test_no_pin_flag_appears_in_this_module():
    """pkcs11-tool takes a card PIN as a command-line argument, where every
    other process on the machine can read it out of the process list. The app
    hands the user the command instead; writing that flag here is how the
    promise would quietly stop being kept."""
    bad = sorted({c for c in _module_constants() if "--pin" in c})
    assert bad == [], f"this page passes a PIN flag: {bad}"
    with open(sc.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "--pin" not in source, "the PIN flag is written somewhere in this module"
