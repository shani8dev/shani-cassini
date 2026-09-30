"""Compatibility shim for the httpx2 migration.

``pyproject.toml`` declares ``httpx2`` as the HTTP client, but the codebase
still writes ``import httpx`` everywhere. ``httpx2`` does NOT provide an
``httpx`` module — it ships ``httpx2`` and an explicit opt-in
``httpx2.alias_httpx()`` that re-exports the httpx2 API under the ``httpx``
name (and ``httpcore`` → ``httpcore2``).

Without this shim, every ``import httpx`` silently resolves to whatever
legacy ``httpx`` happens to be installed on the host (here: 0.28.1). That
makes the tests pass locally but the app would ``ModuleNotFoundError`` on
any clean install — a real dependency bug. Importing this module first
establishes the httpx2-backed alias process-wide.

Usage: ``import shani_cassini._httpx_compat  # noqa: F401`` at the top of any
module that does ``import httpx``.

On a ShaniOS/Arch install the distro ships ``python-httpx``, which the httpx2
API mirrors, so the plain ``httpx`` module is used as is. Arch also ships a
package named ``httpx2`` that is *not* this project and has no ``alias_httpx``,
so a missing attribute has to be treated as a missing httpx2 -- testing only
for ``ModuleNotFoundError`` made the app fail to start on current Arch.
"""

from typing import Callable


def _enable_httpx_alias(import_httpx2: Callable, import_httpx: Callable) -> str:
    """Alias httpx2 under the name httpx when it can; report which one won.

    Both ways this can go wrong are checked, not just the first: httpx2 may be
    absent, or present and be something else entirely. Returns "httpx2" or
    "httpx" so a caller (and a test) can tell which client is live.
    """
    try:
        httpx2 = import_httpx2()
    except ImportError:
        import_httpx()
        return "httpx"
    alias = getattr(httpx2, "alias_httpx", None)
    if alias is None:
        import_httpx()
        return "httpx"
    alias()
    return "httpx2"


_enable_httpx_alias(lambda: __import__("httpx2"), lambda: __import__("httpx"))