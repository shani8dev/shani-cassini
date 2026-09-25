"""Chronoa: the assistant's state and its main switches.

Read straight from Chronoa's own GSettings schema (org.shani.chronoa) -
switches are bound to it, so Chronoa sees a change at once. Chronoa has no
--status/--config command line (the old page ran `shani-chronoa --status`,
which starts the app). API keys in the schema are never shown here.
"""

from __future__ import annotations

import json
import logging
import shutil

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
SCHEMA = "org.shani.chronoa"

SWITCHES = [
    ("privacy-mode", "Privacy mode", "Only local models; nothing leaves this computer"),
    ("auto-start", "Start at login", "Chronoa is ready in the background"),
    ("wake-word-enabled", "Wake word", "Listen for the wake word, hands-free"),
    ("notification-enabled", "Spoken replies", "Read answers and timers aloud"),
    ("cloud-fallback-enabled", "Cloud fallback", "Use a free cloud model when the local one is unavailable"),
]


def _settings():
    src = Gio.SettingsSchemaSource.get_default()
    schema = src.lookup(SCHEMA, True) if src else None
    return Gio.Settings.new_full(schema, None, None) if schema else None


class ChronoaTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._settings = _settings()

        head = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="Chronoa", subtitle="Voice and text assistant")
        img = Gtk.Image.new_from_icon_name("shani-chronoa")
        img.set_pixel_size(48)
        row.add_prefix(img)
        btn = Gtk.Button(label="Open Chronoa", valign=Gtk.Align.CENTER)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: self._open())
        row.add_suffix(btn)
        head.add(row)
        self.append(head)

        if self._settings is None:
            self.append(Adw.StatusPage(icon_name="dialog-warning-symbolic", title="Chronoa's settings are missing",
                                       description=f"The {SCHEMA} schema is not installed."))
            return

        # --- engines
        eng = Adw.PreferencesGroup(title="Engines")
        self._llm = Adw.ActionRow(title="Language model", subtitle="Checking…")
        eng.add(self._llm)
        stt = shutil.which("whisper-cli")
        eng.add(Adw.ActionRow(title="Speech input",
                              subtitle="whisper.cpp" if stt else "Not installed (whisper-cpp)"))
        tts = next((n for b, n in (("piper-tts", "Piper"), ("RHVoice-test", "RHVoice"), ("espeak-ng", "eSpeak NG"))
                    if shutil.which(b)), None)
        eng.add(Adw.ActionRow(title="Speech output", subtitle=tts or "No speech engine installed"))
        self.append(eng)

        # --- switches, bound to GSettings
        sw = Adw.PreferencesGroup(title="Settings")
        keys = set(self._settings.props.settings_schema.list_keys())
        for key, title, sub in SWITCHES:
            if key not in keys:
                continue
            r = Adw.SwitchRow(title=title, subtitle=sub)
            self._settings.bind(key, r, "active", Gio.SettingsBindFlags.DEFAULT)
            sw.add(r)
        for key, title in (("model", "Model"), ("ollama-host", "Ollama address")):
            if key in keys:
                e = Adw.EntryRow(title=title, show_apply_button=True)
                e.set_text(self._settings.get_string(key))
                e.connect("apply", lambda w, k=key: self._settings.set_string(k, w.get_text().strip()))
                sw.add(e)
        self.append(sw)

        self._check_ollama()

    def _check_ollama(self) -> None:
        host = (self._settings.get_string("ollama-host") or "http://localhost:11434").rstrip("/")
        want = self._settings.get_string("model")

        def done(d, err):
            if d is None:
                how = "not running" if shutil.which("ollama") else "not installed (ollama)"
                self._llm.set_subtitle(f"Ollama {how} at {host}")
                return
            models = [m.get("name", "") for m in d.get("models", [])]
            if not models:
                self._llm.set_subtitle("Ollama is running, but has no models yet")
            else:
                self._llm.set_subtitle(GLib.markup_escape_text(
                    f"Ollama: {len(models)} model{'s' * (len(models) != 1)}"
                    + (f" · using {want}" if want else f" · {', '.join(models[:3])}")))
        ss.run_json(["curl", "-fsS", "--max-time", "3", f"{host}/api/tags"], done)

    def _open(self) -> None:
        info = Gio.DesktopAppInfo.new("shani-chronoa.desktop")
        try:
            (info.launch([], None) if info else Gio.Subprocess.new(["shani-chronoa"], Gio.SubprocessFlags.NONE))
        except GLib.Error as e:
            logger.warning("could not start Chronoa: %s", e.message)
