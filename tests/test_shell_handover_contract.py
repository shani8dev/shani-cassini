"""Pin the shani-shell <-> shani-cassini handover contract.

The shell's Settings answers to a fixed set of category ids (see
shani-shell/shani/Modules/Settings/SettingsPage.qml). Cassini's
SHELL_OWNS and settings_row() must only ever name ids from that set,
otherwise open_shell_settings() opens an empty Settings window and the
person lands on "Personalisation" with no explanation.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The category ids shani-shell's Settings answers to, taken from
# shani-shell/shani/Modules/Settings/SettingsPage.qml. Kept here as a
# snapshot so a rename on either side fails this test rather than silently
# degrading.
SHELL_CATEGORIES = {
    "personal", "notifications", "network", "displays", "windows", "sound",
    "access", "input", "time", "apps", "search", "printers", "sharing",
    "backup", "automations", "privacy", "chronoa", "account", "users",
    "power", "about",
}


def test_settings_categories_match_the_shell():
    from shani_cassini.plain import SETTINGS_CATEGORIES

    assert SETTINGS_CATEGORIES == SHELL_CATEGORIES, (
        "Cassini's SETTINGS_CATEGORIES drifted from the shell's. "
        f"missing from Cassini: {SHELL_CATEGORIES - SETTINGS_CATEGORIES}; "
        f"extra in Cassini: {SETTINGS_CATEGORIES - SHELL_CATEGORIES}"
    )


def test_shell_owns_is_a_subset_of_settings_categories():
    from shani_cassini.notebook import SHELL_OWNS

    assert set(SHELL_OWNS) <= SHELL_CATEGORIES, (
        "SHELL_OWNS names a category the shell does not answer to: "
        f"{set(SHELL_OWNS) - SHELL_CATEGORIES}"
    )