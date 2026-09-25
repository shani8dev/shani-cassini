"""Shani Cassini - Main Package"""

# Pin the GI versions before any submodule imports Gtk/Adw (tests import
# submodules directly, not through main.py)
import gi as _gi

_gi.require_version("Gtk", "4.0")
_gi.require_version("Adw", "1")
