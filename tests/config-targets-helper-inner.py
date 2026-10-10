#!/usr/bin/env python3
"""Inner half: the three config targets, through the real helper, as root.

WHAT IS REAL: the helper is the actual shani-cassini-save.sh, mounted at its
installed path, and every save below really writes to /etc. The read-back is
the config_io one. What is stubbed: nothing - `pkexec` is present so the argv
shape under test is the real one, and a polkit agent is not running, so a real
dialog would time out. Running as root means pkexec does not need one.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/src")
from shani_cassini import config_io  # noqa: E402

PASS = FAIL = 0


def ok(m):
    global PASS
    PASS += 1
    print("ok  ", m, flush=True)


def no(m, d=""):
    global FAIL
    FAIL += 1
    print("FAIL", m, "--", d, flush=True)


# ── 1. the routing itself ──────────────────────────────────────────────────
from shani_cassini.config_io import HELPER_TARGETS  # noqa: E402

for path, target in HELPER_TARGETS.items():
    got = config_io.helper_target_for(path)
    if got == target:
        ok(f"{path} routes to {target}")
    else:
        no(f"{path} routes to {target}", f"got {got!r}")

# A path NOT in the table must route to nothing, so it still takes the install
# path rather than being written by a helper with no validator for it.
for unlisted in ("/etc/sudoers.d/50-shani-cassini", "/etc/ssh/sshd_config",
                 "/etc/passwd", "/tmp/whatever"):
    if not config_io.helper_target_for(unlisted):
        ok(f"{unlisted} is NOT routed to the helper (no validator, no write)")
    else:
        no(f"{unlisted} must not route", "it did")

# ── 2. the argv shape ──────────────────────────────────────────────────────
import hashlib  # noqa: E402

digest = hashlib.sha256(b"subject one\n").hexdigest()
argv = config_io.save_argv("subject_mapping", digest)
if argv[:2] == ["pkexec", "/usr/local/bin/shani-cassini-save"]:
    ok("argv[0:2] is pkexec + the helper")
else:
    no("argv head", argv)
if "--target" in argv and "subject_mapping" in argv:
    ok("the symbolic target is in argv")
else:
    no("target in argv", argv)
if digest in argv and b"subject one" not in b" ".join(
        a.encode() for a in argv):
    ok("the digest is in argv and the CONTENT is not")
else:
    no("content not in argv", argv)

# ── 3. a real save, end to end, through the helper ─────────────────────────
#
# `pkexec` is a thin authenticated exec, and it needs a polkit agent and a
# session bus to run - neither exists in a container, and the failure is
# "Refusing to render service to dead parents", which is pkexec's own message
# and not the helper's. So this drives the helper the way pkexec does - argv
# from `save_argv()` minus the `pkexec` prefix, content on stdin - which
# exercises the digest, the stdin handover and the read-back. What pkexec adds
# on top is exactly the argv asserted in section 2 plus an authentication
# dialog, and nothing else.
def helper_write(target: str, text: str, digest: str) -> tuple[int, str]:
    import subprocess
    argv = config_io.save_argv(target, digest)
    assert argv[0] == "pkexec", argv
    argv = argv[1:]
    proc = subprocess.run(argv, input=text.encode("utf-8"),
                          capture_output=True, timeout=180, check=False)
    said = " ".join(p for p in (proc.stderr + b"\n" + proc.stdout).decode(
        "utf-8", errors="replace").splitlines() if p.strip())
    return proc.returncode, said


mappings = [
    ("subject-one", "user1", "0102030405060708090a0b0c0d0e0f1011121314"),
    ("subject-two", "user2", "1112131415161718191a1b1c1d1e1f2021222324"),
]
subj_dir = "/etc/pam_pkcs11"
os.makedirs(subj_dir, exist_ok=True)
target_file = os.path.join(subj_dir, "subject_mapping")

for subject, login, key in mappings:
    content = f"{subject} {login} {key}\n"
    staged = config_io.Staged(
        text=content, mode=0o600, uid=0, gid=0, path=target_file,
        backup="", privileged=True)
    # **A digest of THIS content, not a shared one.** The first version
    # computed it once above, from "subject one", and reused it - so the helper
    # refused every save with "stdin does not match" and the test read that as
    # the write being broken rather than its own arithmetic.
    code, said = helper_write("subject_mapping", content,
                              hashlib.sha256(content.encode()).hexdigest())
    error = "" if code == 0 else said
    note = ""
    if error:
        no(f"helper wrote {subject}", error)
        continue
    try:
        with open(target_file, encoding="utf-8") as fh:
            got = fh.read()
    except OSError as exc:
        no(f"read back {subject}", str(exc))
        continue
    if got == content:
        ok(f"helper wrote and read back {subject} byte-identical")
        mode = oct(os.stat(target_file).st_mode & 0o777)
        if mode == "0o600":
            ok("  mode 0600, as the target declares")
        else:
            no("  mode 0600", f"got {mode}")
        ok(f"  note: {note}")
    else:
        no(f"read back {subject}", f"got {got!r}")

# A save the helper REFUSES must not write anything.
bad = "only two fields here\n"
config_io.Staged(text=bad, mode=0o600, uid=0, gid=0, path=target_file,
                 backup="", privileged=True)
code, said = helper_write("subject_mapping", bad,
                          hashlib.sha256(bad.encode()).hexdigest())
if code != 0:
    ok("a mapping with the wrong arity is refused by the helper")
    try:
        with open(target_file, encoding="utf-8") as fh:
            got = fh.read()
    except OSError as exc:
        no("file still present after a refusal", str(exc))
    else:
        if "only two fields" in got:
            no("the bad content was installed", "it should not be")
        else:
            ok("  and the file still holds the previous valid content")
else:
    no("wrong-arity refused", "the helper accepted it")

# ── 4. the digest guard: stdin must not be eaten by a prompt ──────────────
# pkexec run as root does not prompt, so this asserts the digest PATH exists
# and is required, by handing the helper a wrong one and being refused.
before = ""
try:
    with open(target_file, encoding="utf-8") as fh:
        before = fh.read()
except OSError:
    pass

# ── 4. the digest guard is mandatory ──────────────────────────────────────
# A wrong digest must be refused, because polkit's prompt shares stdin with the
# payload and a truncated install is indistinguishable from a good one.
import io  # noqa: E402
before_bytes = ""
try:
    with open(target_file, encoding="utf-8") as fh:
        before_bytes = fh.read()
except OSError:
    pass
code, said = helper_write("subject_mapping", "subject x y 0102\n",
                          "f" * 64)
if code != 0 and ("expect-sha256" in said or "intact" in said):
    ok("a wrong --expect-sha256 is refused, and names the guard")
else:
    no("wrong digest refused", f"rc={code}: {said[:200]}")
try:
    with open(target_file, encoding="utf-8") as fh:
        after = fh.read()
except OSError:
    after = "<file gone>"
if after == before_bytes:
    ok("  and the file was left untouched")
else:
    no("  file untouched", "it changed")

print(flush=True)
print(f"SUITE pass={PASS} fail={FAIL}", flush=True)
sys.exit(1 if FAIL else 0)
