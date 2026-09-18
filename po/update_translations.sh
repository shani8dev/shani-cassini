#!/usr/bin/env bash
# Regenerate the gettext translation catalogs from POTFILES.in.
# Uses xgettext + msgmerge + msgfmt when available; this script is safe to
# run anywhere those tools are installed.
set -euo pipefail

PO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PO_DIR"

if [[ ! -f POTFILES.in ]]; then
    echo "POTFILES.in not found in $PO_DIR" >&2
    exit 1
fi

if ! command -v xgettext >/dev/null 2>&1; then
    echo "xgettext not found — install gettext to regenerate catalogs" >&2
    exit 1
fi

# Build the file list from POTFILES.in (strip blanks / comments).
FILES=()
while IFS= read -r line; do
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -n $line ]] && FILES+=("$line")
done < POTFILES.in

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "no source files listed in POTFILES.in" >&2
    exit 1
fi

xgettext \
    --from-code=UTF-8 \
    --no-location \
    --omit-header \
    --add-comments=translators: \
    --keyword=_ \
    --keyword=marktr \
    --keyword=N_:1,2 \
    -o shani-gui.pot \
    "${FILES[@]}"

echo "Generated shani-gui.pot with $(grep -c '^msgid ' shani-gui.pot) strings"

for lang in en hi; do
    if [[ -f "${lang}.po" ]]; then
        msgmerge -U --no-location "${lang}.po" shani-gui.pot
        echo "Updated ${lang}.po"
    fi
done

if command -v msgfmt >/dev/null 2>&1; then
    for lang in en hi; do
        msgfmt -c "${lang}.po" -o /dev/null && echo "Checked ${lang}.po grammar"
    done
else
    echo "msgfmt not found — skipping grammar check"
fi

echo "Translation update complete."
