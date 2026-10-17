#!/usr/bin/env bash
# Render every page of Cassini to PNG, on a private (broadway) display.
#
# Mirrors shani-chronoa/tools/render_ui_batch.sh in spirit: own a display,
# sweep every target, report honestly by content, keep logs.

set -uo pipefail

VERBOSE="${VERBOSE:-}"

#: Below this much non-background area, a capture is NOT RENDERED rather than
#: counted as a pass. A blank transparent page and a blank white page both
#: measure 0; the poorest thing that is really a picture measures far above 5.
MIN_CONTENT_PCT="${MIN_CONTENT_PCT:-5}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
RENDERER="$REPO/render_ui.py"

OUTDIR="${1:-/tmp/cassini-ui}"
WIDTH="${2:-1280}"
HEIGHT="${3:-860}"
shift 3 2>/dev/null || shift $#
TARGETS=("$@")

[[ -f $RENDERER ]] || { echo "no renderer at $RENDERER" >&2; exit 1; }
[[ -n ${TARGETS[*]:-} ]] || TARGETS=(pages)

SANDBOX="$(mktemp -d -t cassini-render-XXXXXX)"
mkdir -p "$SANDBOX"/{data,state,config}
START_DISPLAY=""

cleanup() {
    [[ -n $START_DISPLAY ]] && kill "$START_DISPLAY" 2>/dev/null
    rm -rf "$SANDBOX"
}
trap cleanup EXIT

BROADWAY_PORT_BASE=8080

wait_port_free() {
    local num="$1" waited=0 port=$((BROADWAY_PORT_BASE + $1))
    while ss -tln 2>/dev/null | grep -qE ":${port}[[:space:]]"; do
        sleep 0.1
        waited=$((waited + 1))
        [[ $waited -gt 50 ]] && return 1
    done
    return 0
}

start_display() {
    local num="$1"
    setsid gtk4-broadwayd ":$num" >"$SANDBOX/broadway.log" 2>&1 &
    START_DISPLAY=$!
    local waited=0
    while [[ ! -e "/run/user/$(id -u)/broadway$((num + 1)).socket" ]]; do
        sleep 0.2
        waited=$((waited + 1))
        [[ $waited -gt 20 ]] && {
            [[ -n ${VERBOSE:-} ]] && { echo "broadway :$num did not come up:" >&2; sed 's/^/    /' "$SANDBOX/broadway.log" >&2; }
            return 1
        }
    done
    echo ":$num"
}

acquire_display() {
    local n sock port
    for n in $(seq 90 120); do
        sock="/run/user/$(id -u)/broadway$((n + 1)).socket"
        local port=$((BROADWAY_PORT_BASE + n))
        if ss -tln 2>/dev/null | grep -qE ":${port}[[:space:]]"; then
            continue
        fi
        if [[ -S $sock ]]; then
            rm -f "$sock"
        fi
        if start_display "$n" >/dev/null 2>&1; then
            DISP=":$n"
            return 0
        fi
        [[ -n $START_DISPLAY ]] && kill "$START_DISPLAY" 2>/dev/null
        START_DISPLAY=""
        wait_port_free "$n" && rm -f "$sock"
    done
    echo "no free broadway display in :90-:120" >&2
    return 1
}

recycle_display() {
    local old_num="${DISP#:}"
    [[ -n $START_DISPLAY ]] && kill "$START_DISPLAY" 2>/dev/null
    START_DISPLAY=""
    [[ $old_num =~ ^[0-9]+$ ]] && wait_port_free "$old_num"
    acquire_display
}

_png_size() {
    python3 - "$1" "$2" <<'PYSIZE' 2>/dev/null
import sys
try:
    from PIL import Image
except Exception:
    sys.exit(0)
try:
    im = Image.open(sys.argv[1])
except Exception:
    sys.exit(0)
print(im.size[int(sys.argv[2])])
PYSIZE
}
_png_width() { _png_size "$1" 0; }
_png_height() { _png_size "$1" 1; }

_content_percent() {
    python3 - "$1" <<'PYOPACITY' 2>/dev/null
import sys
from collections import Counter
try:
    from PIL import Image
except Exception:
    sys.exit(0)
try:
    im = Image.open(sys.argv[1]).convert("RGBA")
except Exception:
    sys.exit(0)
px = im.load()
w, h = im.size
if w < 1 or h < 1:
    sys.exit(0)
step = 8
TOLERANCE = 8
colours = []
for y in range(0, h, step):
    for x in range(0, w, step):
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        colours.append((r, g, b))
if not colours:
    print(0)
    sys.exit(0)
background = Counter(colours).most_common(1)[0][0]
marks = sum(1 for c in colours
            if max(abs(c[i] - background[i]) for i in range(3)) > TOLERANCE)
print(int(100 * marks / len(colours)))
PYOPACITY
}

_keep_log() {
    local log="$1" out="$2"
    [[ -s $log ]] || return 0
    cp "$log" "${out%.png}.log" 2>/dev/null || return 1
}

render_once() {
    local target="$1"
    local out="$2"
    local log="$SANDBOX/$(echo "$target" | tr '/:' '__').log"
    TARGET="$target" bash -c '
        env -u DISPLAY -u WAYLAND_DISPLAY \
            GDK_BACKEND=broadway BROADWAY_DISPLAY="$1" \
            XDG_DATA_HOME="$2/data" XDG_STATE_HOME="$2/state" \
            XDG_CONFIG_HOME="$2/config" \
            PYTHONDONTWRITEBYTECODE=1 \
            timeout 300 python3 "$3" "$TARGET" "$4" "$5" "$6" >"$7" 2>&1
    ' _ "$DISP" "$SANDBOX" "$RENDERER" "$out" "$WIDTH" "$HEIGHT" "$log" \
        >/dev/null 2>&1

    if ! _keep_log "$log" "$out"; then
        :
    fi
    [[ -s $out ]] || return 1

    # **Warned, not failed.** A render at a different size than was asked for is
    # still a render; refusing would make the harness useless on a box whose
    # display cannot be enlarged, and a check that can never pass stops being
    # read. broadway's screen here is a hard 1024x768, so a 1280x860 request
    # comes back 1024x768 — stated, not inferred from the file.
    #
    # **A taller image is not this warning, and must not be reported as it.**
    # `render_ui.py` now photographs the whole page rather than the window, so a
    # page taller than the viewport comes back at its natural height — and the
    # first version of this note printed "display is smaller" for every one of
    # them, which is the opposite of what happened and would have trained the
    # reader to ignore the line it was added to draw attention to. So the two
    # cases are separated: the width is what the display limited.
    local got_w got_h
    got_w="$(_png_width "$out")"; got_h="$(_png_height "$out")"
    if [[ -n $got_w && -n $got_h ]] && [[ "$got_w" != "$WIDTH" || "$got_h" != "$HEIGHT" ]]; then
        if [[ "$got_h" -gt "$HEIGHT" ]]; then
            # Taller than the window, and narrower because the sidebar's 276px
            # are not part of the page: the page is photographed at its own size,
            # so the line wrapping in the capture is the wrapping a user sees.
            printf 'note: %s captured whole: %sx%s, %spx beyond the %spx window (page width, sidebar excluded)\n' \
                "$(basename "$out")" "$got_w" "$got_h" \
                "$((got_h - HEIGHT))" "$HEIGHT" >&2
        else
            printf 'note: %s captured at %sx%s, not %sx%s (display is smaller)\n' \
                "$(basename "$out")" "$got_w" "$got_h" "$WIDTH" "$HEIGHT" >&2
        fi
    fi

    local content
    content="$(_content_percent "$out")"
    [[ -n $content ]] || return 1
    (( content >= MIN_CONTENT_PCT )) || return 1
    return 0
}

render() {
    local target="$1"
    local out="$2"
    mkdir -p "$(dirname "$out")"
    local best_pct=-1 best_file="" attempt_pct="" last_pct=""
    local n
    for n in 1 2; do
        local try="${out}.try${n}"
        rm -f "$try"
        render_once "$target" "$try" || true
        attempt_pct="$(_content_percent "$try")"
        if [[ -n $attempt_pct ]]; then
            last_pct="$attempt_pct"
            if (( attempt_pct > best_pct )); then
                best_pct="$attempt_pct"
                best_file="$try"
            fi
        fi
        # Stop after the first attempt that clears the floor: a second pass
        # on a recycled display can photograph the default page (overview)
        # instead of the requested one, and its higher content percentage
        # would wrongly win the "best of two".
        if (( attempt_pct >= MIN_CONTENT_PCT )); then
            break
        fi
        (( n < 2 )) && recycle_display
    done
    [[ -n $best_file ]] && mv -f "$best_file" "$out"
    rm -f "${out}.try1" "${out}.try2"

    if (( best_pct >= MIN_CONTENT_PCT )); then
        printf '  PASS  %-28s %8s bytes (%s%% content)\n' \
            "$target" "$(stat -c%s "$out")" "$best_pct"
        return 0
    fi
    if [[ -n $last_pct ]]; then
        printf '  FAIL  %-28s %8s bytes, %s%% content\n' \
            "$target" "$(stat -c%s "$out")" "$last_pct"
    else
        printf '  FAIL  %-28s no file written\n' "$target"
    fi
    return 1
}

page_targets() {
    env -u DISPLAY -u WAYLAND_DISPLAY \
        PYTHONDONTWRITEBYTECODE=1 \
        python3 "$RENDERER" --list pages 2>/dev/null
}

acquire_display || exit 1
echo "cassini render: display $DISP, ${WIDTH}x${HEIGHT}, -> $OUTDIR"
mkdir -p "$OUTDIR"

ok=0; bad=0; failed=()
for t in "${TARGETS[@]}"; do
    case "$t" in
        pages)
            while read -r p; do
                [[ -n $p ]] || continue
                if render "$p" "$OUTDIR/pages/$p.png"; then
                    ok=$((ok + 1))
                else
                    bad=$((bad + 1)); failed+=("$p")
                fi
            done < <(page_targets)
            ;;
        all)
            while read -r p; do
                [[ -n $p ]] || continue
                if render "$p" "$OUTDIR/pages/$p.png"; then
                    ok=$((ok + 1))
                else
                    bad=$((bad + 1)); failed+=("$p")
                fi
            done < <(page_targets)
            ;;
        *)
            name="$t"
            if render "$t" "$OUTDIR/$name.png"; then ok=$((ok + 1)); else bad=$((bad + 1)); failed+=("$t"); fi
            ;;
    esac
done

echo
echo "  $ok rendered, $bad not."
if [[ $bad -gt 0 ]]; then
    printf '  not rendered: %s\n' "${failed[*]}"
fi
exit $(( bad > 0 ? 1 : 0 ))
PY