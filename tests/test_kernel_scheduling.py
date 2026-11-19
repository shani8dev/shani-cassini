"""Kernel page, CPU Scheduling & Games card: what Ananta OS shows on its Gaming
page (the sched_ext scheduler and ntsync), read from the kernel itself.

The sysfs layout is the kernel's (Documentation/scheduler/sched-ext.rst):
/sys/kernel/sched_ext/state is enabled/disabled/enabling/disabling and
root/ops names the running BPF scheduler. This host's own state file reads
"disabled" (measured 2026-11-19). Each case points the module's paths at a
scratch tree; the card stays read-only (TestKernelTab holds "no buttons").
"""
import pytest

from shani_cassini.tabs import kernel


@pytest.fixture
def paths(tmp_path, monkeypatch):
    sx = tmp_path / "sched_ext"
    monkeypatch.setattr(kernel, "SCHED_EXT_DIR", str(sx))
    monkeypatch.setattr(kernel, "SCX_LOADER_BIN", str(tmp_path / "scx_loader"))
    monkeypatch.setattr(kernel, "SCX_LOADER_CONF", str(tmp_path / "scx_loader.toml"))
    monkeypatch.setattr(kernel, "NTSYNC_DEV", str(tmp_path / "ntsync"))
    return tmp_path, sx


def test_no_sched_ext_in_the_kernel(paths):
    assert "no sched_ext" in kernel._scheduler_text()


def test_sched_ext_present_but_off(paths):
    _, sx = paths
    sx.mkdir(); (sx / "state").write_text("disabled\n")
    assert kernel._scheduler_text().startswith("The kernel's own (EEVDF); no sched_ext")


def test_a_running_scheduler_is_named_as_the_kernel_names_it(paths):
    _, sx = paths
    (sx / "root").mkdir(parents=True)
    (sx / "state").write_text("enabled\n")
    (sx / "root" / "ops").write_text("lavd_1.0.13_x86_64_unknown_linux_gnu\n")
    assert kernel._scheduler_text() == "lavd_1.0.13_x86_64_unknown_linux_gnu (sched_ext)"


def test_scx_loader_absent_says_it_is_not_in_the_image(paths):
    assert kernel._scx_loader_text().startswith("Not installed")


def test_scx_loader_present_reports_the_configured_default(paths):
    tmp, _ = paths
    (tmp / "scx_loader").write_text("")
    # shani-settings' own file
    (tmp / "scx_loader.toml").write_text('default_sched = "scx_lavd"\n')
    assert kernel._scx_loader_text() == "scx_loader installed; default scx_lavd (scxctl switches it)"


def test_ntsync(paths):
    tmp, _ = paths
    assert kernel._ntsync_text().startswith("Not available")
    (tmp / "ntsync").write_text("")
    assert kernel._ntsync_text().startswith("Available")


def test_the_card_is_filled_on_the_page(paths):
    from shani_cassini.tabs.kernel import KernelTab
    from shani_cassini.widgets import find_named
    tab = KernelTab()
    for name in ("k-sched", "k-scx-loader", "k-ntsync"):
        assert find_named(tab, name).get_label(), name
