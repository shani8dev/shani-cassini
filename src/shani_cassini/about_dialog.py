"""About Shani Cassini (Adw.AboutDialog - the libadwaita one)."""

from __future__ import annotations

from gi.repository import Adw, Gtk  # type: ignore

VERSION = "0.1.0"


def about_dialog() -> Adw.AboutDialog:
    return Adw.AboutDialog(
        application_name="Shani Cassini",
        application_icon="dev.shani.cassini",
        developer_name="The Shanios developers",
        version=VERSION,
        comments="Keeps a Shanios system updated, healthy and recoverable.",
        website="https://docs.shani.dev/system/cassini",
        support_url="https://docs.shani.dev/troubleshooting",
        issue_url="https://github.com/shani8dev/shani-cassini/issues",
        license_type=Gtk.License.GPL_3_0_ONLY,
        copyright="© 2026 The Shanios developers",
    )
