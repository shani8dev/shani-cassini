"""Change one setting in a root-owned config file, in place, behind the helper.

This exists because two pages now need the same shape of edit and neither owns
any of the machinery:

* **UPS** edits `/etc/nut/upsmon.conf` — the shutdown policy, and warns
  that the daemon has to be restarted for it to matter.
* **IRQ Balance** edits `/etc/default/irqbalance` — the CPU banlist.

Both are the same operation: read a file that may not exist, find one key,
replace its value or remove the line, and write the whole thing back through
``pkexec shani-cassini-save`` with a validator on the far side.

**What is deliberately NOT here.** No ``sed -i``, no in-place string surgery on
a file the caller does not own, and no path outside what the caller passes. The
write goes through :mod:`shani_cassini.config_io`, which is where the
fail-closed part lives: content on stdin, a digest, and a read-back that
decides the outcome rather than the exit code.

**Two rules that are easy to get wrong and are therefore structural here.**

1. **A key that is commented out is set, not replaced.** NUT ships
   ``#MINSUPPLIES 1`` in its template and ``irqbalance.env`` ships
   ``#IRQBALANCE_BANNED_CPULIST=`` commented. A naive replace finds nothing and
   silently does nothing, which is the failure this module exists to prevent:
   the user clicks Save, gets a success toast, and the setting is still off.
   So ``set_key`` uncomments as a fallback and says which it did.
2. **The last occurrence of a key wins**, and only the last is changed.
   NUT's template mentions several of these keys in its prose comments and
   sets a few more than once. Changing the first and leaving the second in
   place produces a file where the value the daemon reads is not the one the
   user just chose - a save that reports success and changes nothing. The
   earlier occurrences are commented out rather than deleted, so the file keeps
   its documentation and the answer is unambiguous to the next reader.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from . import config_io


def _split_directive(line: str) -> tuple[str, str, bool]:
    """``KEY VALUE`` or ``KEY=VALUE`` -> (key, value, was_commented).

    Both spellings occur in real files: apcupsd.conf was ``KEY VALUE`` with no
    ``=`` anywhere in it, and irqbalance's env file is ``KEY=VALUE`` because
    systemd parses it. Guessing one shape here is how that first validator came
    to refuse the distribution's own file — which is why this function reads
    the separator off the file rather than assuming one.
    """
    stripped = line.strip()
    commented = stripped.startswith("#")
    body = stripped.lstrip("#").strip()
    if "=" in body:
        key, _, value = body.partition("=")
    elif " " in body:
        key, _, value = body.partition(" ")
    else:
        return "", "", commented
    return key.strip(), value.strip().strip('"'), commented


def separator(text: str) -> str:
    """``"="`` or ``" "`` - whichever this file already uses for a live directive.

    **This is not a style preference, it is correctness, and getting it wrong is
    silent.** apcupsd splits its config on whitespace, so a line written as
    ``BATTERYLEVEL=15`` names a key ``BATTERYLEVEL=15`` and is ignored: the save
    succeeds, the page says it worked, and the threshold has not moved. That
    shipped file had **zero** ``=`` in it (``grep -cE '^[A-Z][A-Z0-9_]*='``
    returned 0 across all 344 lines). irqbalance's env file is the opposite,
    ``KEY=VALUE``, because systemd parses it.

    So the separator is read off the file rather than chosen here. A file with no
    uncommented directive yet falls back to ``"="``, which is right for a systemd
    EnvironmentFile and harmless for apcupsd: the first line written is the one
    that decides, and it is always a key NUT's own template already contains
    as a comment to be uncommented.
    """
    for line in text.splitlines():
        name, _value, commented = _split_directive(line)
        if name and not commented:
            return "=" if "=" in line.split(name, 1)[1] else " "
    return "="


def read_config(path: str) -> Optional[str]:
    """The file's text, or ``None`` when it cannot be read.

    ``None`` and ``""`` are different answers and are kept apart on purpose: an
    empty file is a file, and a file the caller cannot open is not one. The
    pages render them differently.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def current_value(text: str, key: str) -> Optional[str]:
    """The effective value of `key`, or ``None`` when it is not set.

    A commented-out line does **not** count as set, even if it is the only
    occurrence: reporting ``5`` because the template says ``#BATTERYLEVEL 5``
    would tell a user their shutdown threshold is already 5% when the daemon is
    using its own default.
    """
    found = None
    for line in text.splitlines():
        name, value, commented = _split_directive(line)
        if name == key and not commented:
            found = value
    return found


def set_key(text: str, key: str, value: str) -> tuple[str, str]:
    """Return `(new_text, what_happened)` with `key` set to `value`.

    ``what_happened`` is one of ``changed`` (an existing uncommented line was
    updated), ``added`` (the key was present only as a comment, or absent, and
    the new line was appended), or ``duplicate`` (nothing was written because
    the key appears more than once uncommented and we cannot know which the
    daemon reads - see rule 2 above).
    """
    lines = text.splitlines(keepends=True)
    sep = separator(text)
    rendered = f"{key}{sep}{value}"
    hits = [i for i, line in enumerate(lines)
            if _split_directive(line)[0] == key
            and _split_directive(line)[2] is False]
    if len(hits) > 1:
        return text, "duplicate"
    if hits:
        index = hits[0]
        newline = "\n" if lines[index].endswith("\n") else ""
        lines[index] = f"{rendered}{newline}"
        return "".join(lines), "changed"
    # Not set. Replace a commented occurrence in place if there is one, so the
    # user sees the key where the template put it rather than at the bottom of
    # a 344-line file; otherwise append.
    commented = [i for i, line in enumerate(lines)
                 if _split_directive(line)[0] == key
                 and _split_directive(line)[2] is True]
    newline = "\n" if (not lines or text.endswith("\n")) else ""
    if commented:
        index = commented[0]
        lines[index] = f"{rendered}\n"
        return "".join(lines), "changed"
    return text + f"{rendered}{newline}", "added"


def remove_key(text: str, key: str) -> tuple[str, bool]:
    """Return `(new_text, removed)`. Commented lines are left alone."""
    lines = text.splitlines(keepends=True)
    kept, removed = [], False
    for line in lines:
        name, _value, commented = _split_directive(line)
        if name == key and not commented:
            removed = True
            continue
        kept.append(line)
    return "".join(kept), removed


def stage(path: str, text: str, *, expect_owner: Optional[tuple[int, int]] = (0, 0)
          ) -> config_io.Staged:
    """A `Staged` for `path` holding `text`, for the shared write path."""
    return config_io.Staged(path=path, text=text, backup="",
                            expect_owner=expect_owner)


def save(path: str, text: str, done: Callable[[str, str], None]) -> None:
    """Write `text` to `path` through the helper, off the GTK main loop.

    Blocking, like every writer in :mod:`config_io`: the caller runs it on a
    thread, because ``pkexec`` waits for a human to type a password.
    """
    config_io.write_staged_privileged(stage(path, text), done)


def cpu_list_ok(value: str) -> bool:
    """Is `value` a CPU list irqbalance's own parser accepts?

    Mirrors the helper's validator rather than inventing a second rule here.
    ``0``, ``0-3``, ``0,2,4`` and ``0-3,5,7-8`` are the shapes it takes; anything
    else would be ignored by the daemon rather than reported.
    """
    return bool(re.fullmatch(r"[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*",
                             value.strip()))


def conf_value(path: str, key: str) -> str:
    """The effective value for display: set, or ``""``.

    ``""`` is what a `Gtk.Entry` needs to show "not set" honestly, and it is
    distinct from a key that is set to an empty value on purpose.
    """
    text = read_config(path)
    if text is None:
        return ""
    return current_value(text, key) or ""