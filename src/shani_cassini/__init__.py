"""Shani Cassini - Main Package.

The background agent runs without a display, so GI is not imported when the
process was started with ``--agent``. GUI entry points pin the versions they
use before importing Adw or Gtk.
"""

import sys

if "--agent" not in sys.argv[1:]:
    import gi as _gi

    _gi.require_version("Gtk", "4.0")
    _gi.require_version("Adw", "1")
