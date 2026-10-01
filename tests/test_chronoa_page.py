"""Chronoa's page must not quietly lose a control.

A `*-sense-enabled` style key that is in the schema XML but missing from
gschemas.compiled can never be read or written, and gsettings reads only the
compiled file. The page used to `continue` past any such key, so a broken
install rendered as a build that simply did not have that setting - the
"looks merely absent" failure the senses hit, one layer up.
"""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from shani_cassini.tabs import chronoa as tab_mod  # noqa: E402


class _Schema:
    def __init__(self, keys):
        self._keys = list(keys)

    def list_keys(self):
        return list(self._keys)


class _Settings:
    """Enough of Gio.Settings for the page, with a schema we choose.

    Real Gio.Settings would need a real compiled schema on disk; what is under
    test is the page's reaction to a key list, not GSettings itself. get_string
    raises on a key the schema does not declare, exactly as the real one does -
    so a page that reads an absent key fails here instead of in a slot.
    """

    def __init__(self, keys):
        self._keys = set(keys)
        self.props = type("Props", (), {"settings_schema": _Schema(keys)})()
        self.bound = []

    def bind(self, key, obj, prop, flags):
        assert key in self._keys, f"bound an undeclared key: {key}"
        self.bound.append(key)

    def get_string(self, key):
        if key not in self._keys:
            raise KeyError(f"key {key!r} is not in the schema")
        return ""

    def set_string(self, key, value):
        if key not in self._keys:
            raise KeyError(f"key {key!r} is not in the schema")


def _all_rows(widget, out=None):
    """Every Adw row under `widget`.

    Filters on the type rather than duck-typing `get_title()`: the walk also
    returns the plain Gtk.Boxes libadwaita lays rows out in, and asking one for
    a title is an AttributeError, not a False.
    """
    out = [] if out is None else out
    child = widget.get_first_child()
    while child:
        if isinstance(child, Adw.PreferencesRow):
            out.append(child)
        _all_rows(child, out)
        child = child.get_next_sibling()
    return out


class TestAbsentKeys:
    def test_it_reports_only_what_the_compiled_schema_lacks(self):
        wanted = ["privacy-mode", "model", "nope"]
        assert tab_mod.absent_keys(wanted, ["privacy-mode", "model"]) == ["nope"]

    def test_nothing_absent_is_the_healthy_case(self):
        wanted = [k for k, _t, _s in tab_mod.SWITCHES] + [k for k, _t in tab_mod.ENTRIES]
        assert tab_mod.absent_keys(wanted, wanted) == []


class TestPageWithACompleteSchema:
    @pytest.fixture
    def page(self, monkeypatch):
        wanted = [k for k, _t, _s in tab_mod.SWITCHES] + [k for k, _t in tab_mod.ENTRIES]
        monkeypatch.setattr(tab_mod, "_settings", lambda: _Settings(wanted))
        return tab_mod.ChronoaTab()

    def test_every_declared_switch_gets_a_row(self, page):
        titles = {r.get_title() for r in _all_rows(page)}
        for _k, title, _s in tab_mod.SWITCHES:
            assert title in titles, f"no row for {title}"

    def test_no_complaint_row_when_the_schema_is_complete(self, page):
        titles = {r.get_title() for r in _all_rows(page)}
        assert "Some settings are unavailable" not in titles


class TestPageWithKeysMissingFromTheCompiledSchema:
    @pytest.fixture
    def page(self, monkeypatch):
        # `model` and `wake-word-enabled` are dropped - the model/ollama-host
        # pair also drives _check_ollama, which used to raise on them.
        kept = [k for k, _t, _s in tab_mod.SWITCHES if k != "wake-word-enabled"]
        monkeypatch.setattr(tab_mod, "_settings", lambda: _Settings(kept))
        return tab_mod.ChronoaTab()

    def test_the_page_still_constructs(self, page):
        """The crash this pins: get_string() on an undeclared key raises, and
        _check_ollama read both entries unconditionally."""
        assert isinstance(page, Gtk.Box)

    def test_a_missing_control_is_named_rather_than_vanished(self, page):
        text = " ".join(
            f"{r.get_title()} {r.get_subtitle()}"
            for r in _all_rows(page)
            if hasattr(r, "get_subtitle")
        )
        assert "Some settings are unavailable" in text
        assert "wake-word-enabled" in text, (
            "the row must name the key, so a user can tell a broken install "
            "from a build that never had the setting"
        )

    def test_the_healthy_rows_are_still_there(self, page):
        titles = {r.get_title() for r in _all_rows(page)}
        assert "Privacy mode" in titles

    def test_the_ollama_check_never_reads_an_undeclared_key(self, page):
        """The actual crash this pins.

        `Gio.Settings.get_string()` raises on a key the compiled schema does
        not declare, and `_check_olloma` read `ollama-host` and `model`
        unconditionally - so the silent `continue` above was hiding a page that
        could not finish constructing. Re-running it with both keys absent must
        not raise; the row keeps its placeholder until the async reply lands,
        which is correct and is why no assertion is made about the subtitle.
        """
        page._check_ollama(keys=frozenset())
        # And with the key set the page really has - _check_ollama trusts the
        # argument it is given, so passing a key the schema lacks would be
        # testing the test's lie rather than the page.
        page._check_ollama(keys={"privacy-mode"})


class TestWakePhrase:
    """Chronoa's wake phrase is whisper.cpp: the page says what it needs and what to say."""

    def test_the_status_names_what_is_missing(self):
        assert "whisper-cpp" in tab_mod.wake_phrase_status(None, [], "hey chronoa")
        assert "model" in tab_mod.wake_phrase_status("/usr/bin/whisper-cli", [], "hey chronoa")

    def test_a_ready_engine_says_the_phrase_and_the_model(self):
        s = tab_mod.wake_phrase_status("/usr/bin/whisper-cli", ["/m/ggml-tiny-q5_1.bin"], "hey chronoa")
        assert "hey chronoa" in s and "ggml-tiny-q5_1.bin" in s

    def test_models_are_found_where_chronoa_looks(self, monkeypatch, tmp_path):
        d = tmp_path / "whisper" / "models"
        d.mkdir(parents=True)
        (d / "ggml-base-q5_1.bin").write_bytes(b"x")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert str(d / "ggml-base-q5_1.bin") in tab_mod.whisper_models()

    def test_the_page_has_the_phrase_entry_and_the_engine_row(self, monkeypatch):
        wanted = [k for k, _t, _s in tab_mod.SWITCHES] + [k for k, _t in tab_mod.ENTRIES]
        assert "wake-phrase" in wanted
        monkeypatch.setattr(tab_mod, "_settings", lambda: _Settings(wanted))
        titles = {r.get_title() for r in _all_rows(tab_mod.ChronoaTab())}
        assert {"Wake phrase", "Wake phrase engine"} <= titles

    def test_an_older_chronoa_without_the_key_still_builds(self, monkeypatch):
        kept = [k for k, _t, _s in tab_mod.SWITCHES] + ["model", "ollama-host"]
        monkeypatch.setattr(tab_mod, "_settings", lambda: _Settings(kept))
        rows = _all_rows(tab_mod.ChronoaTab())
        text = " ".join(f"{r.get_title()} {r.get_subtitle() if hasattr(r, 'get_subtitle') else ''}" for r in rows)
        assert "Wake phrase engine" in text and "wake-phrase" in text, "the absent key is named"
