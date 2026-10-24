"""Namespace shim: the chart widgets live in ``shani_cassini.charts``.

This package mirrors the chronoa layout some consumers expect; the one
implementation is upstream of it. A duplicate body here drifted the moment
shani-cassini's chart module grew (Batch-59 render gate, 2026-10-24), so the
module re-exports instead of carrying its own copy.
"""
from shani_cassini.charts import *  # noqa: F401,F403
