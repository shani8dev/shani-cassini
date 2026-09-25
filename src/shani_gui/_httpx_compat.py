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

Usage: ``import shani_gui._httpx_compat  # noqa: F401`` at the top of any
module that does ``import httpx``.

On a ShaniOS/Arch install there is no httpx2 package - the distro ships
``python-httpx``, which the httpx2 API mirrors - so without httpx2 the
plain ``httpx`` module is used as is.
"""

try:
    import httpx2
except ModuleNotFoundError:
    import httpx  # noqa: F401  (python-httpx: the packaged dependency)
else:
    httpx2.alias_httpx()