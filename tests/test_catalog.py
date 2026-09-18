"""Tests for the TOML-driven application catalog."""

from __future__ import annotations

import pytest

from shani_gui.catalog import CatalogApp, load_apps, app_package_for


class TestLoadApps:
    """Tests for load_apps()."""

    def test_load_apps_returns_list(self) -> None:
        apps = load_apps()
        assert isinstance(apps, list)

    def test_load_apps_non_empty(self) -> None:
        apps = load_apps()
        assert len(apps) > 0

    def test_load_apps_returns_catalog_apps(self) -> None:
        apps = load_apps()
        for app in apps:
            assert isinstance(app, CatalogApp)

    def test_load_apps_has_expected_fields(self) -> None:
        apps = load_apps()
        for app in apps:
            assert app.id
            assert app.title
            assert isinstance(app.summary, str)
            assert isinstance(app.group, str)
            assert isinstance(app.packages, dict)
            assert app.flatpak is None or isinstance(app.flatpak, str)

    def test_load_apps_contains_firefox(self) -> None:
        apps = load_apps()
        ids = [a.id for a in apps]
        assert "firefox" in ids

    def test_load_apps_contains_all_six(self) -> None:
        apps = load_apps()
        ids = {a.id for a in apps}
        assert ids == {"firefox", "chromium", "codecs", "libreoffice", "steam", "vlc"}

    def test_load_apps_sorted_by_filename(self) -> None:
        apps = load_apps()
        ids = [a.id for a in apps]
        assert ids == ["chromium", "codecs", "firefox", "libreoffice", "steam", "vlc"]

    def test_load_apps_flatpak_optional(self) -> None:
        apps = load_apps()
        by_id = {a.id: a for a in apps}
        assert by_id["firefox"].flatpak == "org.mozilla.firefox"
        assert by_id["codecs"].flatpak is None

    def test_load_apps_packages_populated(self) -> None:
        apps = load_apps()
        by_id = {a.id: a for a in apps}
        assert by_id["firefox"].packages["arch"] == "firefox"
        assert by_id["firefox"].packages["debian"] == "firefox"
        assert by_id["firefox"].packages["suse"] == "MozillaFirefox"


class TestAppPackageFor:
    """Tests for app_package_for()."""

    def test_resolves_arch_package(self) -> None:
        apps = load_apps()
        firefox = next(a for a in apps if a.id == "firefox")
        assert app_package_for(firefox, "arch") == "firefox"

    def test_resolves_debian_package(self) -> None:
        apps = load_apps()
        firefox = next(a for a in apps if a.id == "firefox")
        assert app_package_for(firefox, "debian") == "firefox"

    def test_resolves_suse_package(self) -> None:
        apps = load_apps()
        firefox = next(a for a in apps if a.id == "firefox")
        assert app_package_for(firefox, "suse") == "MozillaFirefox"

    def test_falls_back_to_arch(self) -> None:
        apps = load_apps()
        firefox = next(a for a in apps if a.id == "firefox")
        assert app_package_for(firefox, "solaris") == "firefox"

    def test_returns_none_for_no_match(self) -> None:
        app = CatalogApp(
            id="test",
            title="Test",
            summary="Test app",
            group="Test",
            packages={},
            flatpak=None,
        )
        assert app_package_for(app, "arch") is None
        assert app_package_for(app, "debian") is None

    def test_returns_none_when_no_arch_fallback(self) -> None:
        app = CatalogApp(
            id="test",
            title="Test",
            summary="Test app",
            group="Test",
            packages={"debian": "test-pkg"},
            flatpak=None,
        )
        assert app_package_for(app, "arch") is None
        assert app_package_for(app, "debian") == "test-pkg"
