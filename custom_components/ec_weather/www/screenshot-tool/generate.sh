#!/usr/bin/env bash
# Regenerate the card's release screenshots headlessly.
#
#   ./generate.sh [output-dir]
#
# Renders page.html (synthetic fixture, ha-icon shim) in headless Chromium
# for each view × viewport × theme, sizing the window to the measured content
# height, at 2x scale for crisp PNGs. Default output: ../../screenshots/.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/../../screenshots}"
mkdir -p "$OUT"

BROWSER="${SCREENSHOT_BROWSER:-/Applications/Helium.app/Contents/MacOS/Helium}"
if [[ ! -x "$BROWSER" ]]; then
    echo "No Chromium at $BROWSER — set SCREENSHOT_BROWSER" >&2
    exit 1
fi

FLAGS=(--headless=new --disable-gpu --no-first-run --allow-file-access-from-files
       --hide-scrollbars --force-device-scale-factor=2)

measure_height() {  # $1=url $2=width
    "$BROWSER" "${FLAGS[@]}" --window-size="$2",4000 --virtual-time-budget=8000 \
        --dump-dom "$1" 2>/dev/null \
        | grep -o '<pre id="MEASURE"[^>]*>[^<]*</pre>' \
        | grep -o '{[^}]*}' | grep -o '[0-9]\+'
}

shoot() {
    local name="$1" view="$2" width="$3" theme="$4"
    local url="file://$HERE/page.html?view=$view&theme=$theme"
    # Phone widths: pin the card (window minus 2x24 padding) — Chromium's
    # ~515px minimum window width makes small viewports lie otherwise.
    if (( width < 500 )); then url="$url&cardwidth=$(( width - 48 ))"; fi
    local height
    height="$(measure_height "$url" "$width")"
    if [[ -z "$height" ]]; then
        echo "FAILED to measure $name" >&2
        return 1
    fi
    # Popups overlay the viewport: cap at a phone/laptop-ish height so the
    # scrim frames the dialog instead of stretching the page.
    if [[ "$view" == "popup" ]]; then
        if (( width < 500 )); then height=844; else height=$(( height > 1100 ? 1100 : height )); fi
    fi
    "$BROWSER" "${FLAGS[@]}" --window-size="$width,$height" --virtual-time-budget=8000 \
        --screenshot="$OUT/$name.png" "$url" 2>/dev/null
    echo "wrote $OUT/$name.png (${width}x${height}@2x)"
}

THEMES=(${SCREENSHOT_THEMES:-dark})
for theme in "${THEMES[@]}"; do
    suffix=""
    [[ "$theme" != "dark" ]] && suffix="-$theme"
    shoot "dashboard$suffix"        dashboard 760 "$theme"
    shoot "popup$suffix"            popup     940 "$theme"
    shoot "dashboard-mobile$suffix" dashboard 390 "$theme"
    shoot "popup-mobile$suffix"     popup     390 "$theme"
done

# Doc composition: one landscape overview per theme — desktop + mobile +
# mobile popup side by side at a common height. A single image carries three
# viewports so info.md keeps its text structure instead of a screenshot scroll.
for theme in "${THEMES[@]}"; do
    suffix=""
    [[ "$theme" != "dark" ]] && suffix="-$theme"
    bg="#0b1220"
    [[ "$theme" == "light" ]] && bg="#dde5ee"
    tmp="$(mktemp -d)"
    for part in dashboard dashboard-mobile popup-mobile; do
        magick "$OUT/$part$suffix.png" -resize x2000 "$tmp/$part.png"
    done
    # +append (not montage): montage insists on resolving a font even without
    # labels and exits non-zero on machines without one configured.
    magick "$tmp/dashboard.png" "$tmp/dashboard-mobile.png" "$tmp/popup-mobile.png" \
        -bordercolor "$bg" -border 16 -background "$bg" +append -quality 90 "$OUT/overview$suffix.webp"
    rm -rf "$tmp"
    echo "wrote $OUT/overview$suffix.webp"
done
