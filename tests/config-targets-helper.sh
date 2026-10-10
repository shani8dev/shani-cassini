#!/usr/bin/env bash
# Proves config_io's three new targets actually reach shani-cassini-save, and
# that the read-back - not the exit code - decides.
#
# Runs in a privileged container because the helper requires root
# (`(( EUID == 0 )) || die "must run as root"`), and calling it as the user this
# suite normally runs as would test the refusal instead of the write.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAVE_SRC="$REPO_ROOT/../shani-deploy/scripts/shani-cassini-save.sh"
[[ -f "$SAVE_SRC" ]] || { echo "no helper at $SAVE_SUM" >&2; exit 1; }
exec docker run --rm --privileged \
    -v "$REPO_ROOT/src:/src:ro" \
    -v "$SAVE_SRC:/usr/local/bin/shani-cassini-save:ro" \
    -v "$SCRIPT_DIR/config-targets-helper-inner.py:/inner.py:ro" \
    cassini-ux:latest bash -c '
pacman -Sy --noconfirm >/dev/null 2>&1
command -v pkexec >/dev/null || pacman -S --noconfirm --needed polkit >/dev/null 2>&1
# The page modules are not needed here: config_io is imported directly, so the
# GTK stack is not loaded and this runs as fast as a shell test.
PYTHONPATH=/src python3 /inner.py
'
