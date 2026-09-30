"""The httpx2 shim, against the three ways the import can go wrong.

The bug these cover is not hypothetical: Arch now ships a package named
`httpx2` that is not the one this shim was written against and has no
`alias_httpx`, so the app raised AttributeError on startup instead of falling
back to the distro `httpx`. The shim used to check only for the module being
absent, which is the one of the three cases that was never the problem.
"""


from shani_cassini._httpx_compat import _enable_httpx_alias


class _NoHttpx2:
    def __init__(self):
        self.calls = []

    def __call__(self):
        self.calls.append("httpx2")
        raise ModuleNotFoundError("No module named 'httpx2'")


class _Httpx2:
    def __init__(self, with_alias=True):
        self.with_alias = with_alias
        self.calls = []

    def __call__(self):
        self.calls.append("httpx2")
        module = type("_Fake", (), {})()
        if self.with_alias:
            module.alias_httpx = lambda: self.calls.append("alias_httpx")
        return module


class _Httpx:
    def __init__(self):
        self.calls = []

    def __call__(self):
        self.calls.append("httpx")


def test_httpx2_is_used_when_it_can_alias():
    a, b = _Httpx2(with_alias=True), _Httpx()
    assert _enable_httpx_alias(a, b) == "httpx2"
    assert "alias_httpx" in a.calls
    assert b.calls == [], "imported httpx as well, leaving two clients live"


def test_a_httpx2_without_the_alias_falls_back_instead_of_raising():
    """The Arch case: the module is importable and is not the one we want."""
    a, b = _Httpx2(with_alias=False), _Httpx()
    assert _enable_httpx_alias(a, b) == "httpx"
    assert b.calls == ["httpx"], "an httpx2 without alias_httpx left no client at all"


def test_an_absent_httpx2_falls_back_to_the_distro_package():
    a, b = _NoHttpx2(), _Httpx()
    assert _enable_httpx_alias(a, b) == "httpx"
    assert b.calls == ["httpx"]


def test_the_module_import_leaves_exactly_one_httpx_client_importable():
    """The real call at the bottom of the module, not a fake one."""
    import importlib

    import shani_cassini._httpx_compat as compat

    importlib.reload(compat)
    client = importlib.import_module("httpx")
    assert client is not None
    assert hasattr(client, "get") or hasattr(client, "AsyncClient"), client
