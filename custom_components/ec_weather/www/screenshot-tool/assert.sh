#!/usr/bin/env bash
# T2 render smoke — assertion mode.
#
#   ./assert.sh [dump-dir]
#
# Renders page.html (the same synthetic fixture + ha-icon shim the screenshots
# use) in headless Chromium for every view × theme × viewport the generator
# enumerates, and for each combination asserts:
#   1. the page's #ERRORS collector is empty ("[]") — no window.onerror,
#      unhandledrejection, or console.error fired while the card rendered;
#   2. the measured content height sits inside sane per-view bounds — a cheap
#      proxy for "the card actually painted" (catches a collapsed 0px render
#      or a runaway layout), NOT a pixel-perfect regression.
#
# On any failure the offending serialized DOM is written to [dump-dir] (default
# ./dump/) so CI can upload it as an artifact, and the script exits non-zero.
#
# Browser resolution mirrors generate.sh: SCREENSHOT_BROWSER, defaulting to the
# mac Helium path locally and to google-chrome on CI runners where Helium is
# absent (GitHub ubuntu images preinstall Chrome).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DUMP_DIR="${1:-$HERE/dump}"

BROWSER="${SCREENSHOT_BROWSER:-/Applications/Helium.app/Contents/MacOS/Helium}"
if [[ ! -x "$BROWSER" ]]; then
    # Fall back to a Chrome/Chromium on PATH (CI runners preinstall one).
    for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BROWSER="$(command -v "$candidate")"
            break
        fi
    done
fi
if [[ ! -x "$BROWSER" ]] && ! command -v "$BROWSER" >/dev/null 2>&1; then
    echo "No Chromium at '$BROWSER' — set SCREENSHOT_BROWSER" >&2
    exit 1
fi

# --no-sandbox: CI runners run Chrome as a user without a usable sandbox; the
# flag is harmless to the local Helium run and required on GitHub ubuntu images.
FLAGS=(--headless=new --disable-gpu --no-sandbox --no-first-run --allow-file-access-from-files
       --hide-scrollbars --force-device-scale-factor=2)

# Per-view sane height bounds (px), derived from real local measurements
# (desktop ≈ 1273, mobile ≈ 1460 as of the current card + fixture) with wide
# margin: the assertion catches a broken render, not fixture-content drift.
DESKTOP_MIN=600
DESKTOP_MAX=2600
MOBILE_MIN=700
MOBILE_MAX=2900

FAILURES=0

check() {  # $1=name $2=view $3=width $4=theme
    local name="$1" view="$2" width="$3" theme="$4"
    local url="file://$HERE/page.html?view=$view&theme=$theme"
    # Phone widths: pin the card as generate.sh does, so Chromium's ~515px
    # minimum window width doesn't distort small viewports.
    if (( width < 500 )); then url="$url&cardwidth=$(( width - 48 ))"; fi

    local dom
    dom="$("$BROWSER" "${FLAGS[@]}" --window-size="$width",4000 \
        --virtual-time-budget=8000 --dump-dom "$url" 2>/dev/null)" || true

    local errors height min max ok=1
    errors="$(printf '%s' "$dom" \
        | grep -o '<pre id="ERRORS"[^>]*>[^<]*</pre>' \
        | sed -E 's/<pre[^>]*>//; s#</pre>##')"
    height="$(printf '%s' "$dom" \
        | grep -o '<pre id="MEASURE"[^>]*>[^<]*</pre>' \
        | grep -o '{[^}]*}' | grep -o '[0-9]\+')"

    if (( width < 500 )); then min=$MOBILE_MIN; max=$MOBILE_MAX
    else min=$DESKTOP_MIN; max=$DESKTOP_MAX; fi

    if [[ -z "$errors" ]]; then
        echo "FAIL $name — #ERRORS node missing (page never rendered)" >&2
        ok=0
    elif [[ "$errors" != "[]" ]]; then
        echo "FAIL $name — JS errors: $errors" >&2
        ok=0
    fi

    if [[ -z "$height" ]]; then
        echo "FAIL $name — no #MEASURE height (render did not settle)" >&2
        ok=0
    elif (( height < min || height > max )); then
        echo "FAIL $name — height ${height}px outside [$min,$max]" >&2
        ok=0
    fi

    if (( ok )); then
        echo "PASS $name — height ${height}px, no errors"
    else
        mkdir -p "$DUMP_DIR"
        printf '%s' "$dom" > "$DUMP_DIR/$name.html"
        echo "     dumped DOM -> $DUMP_DIR/$name.html" >&2
        FAILURES=$((FAILURES + 1))
    fi
}

THEMES=(${SCREENSHOT_THEMES:-dark light})
for theme in "${THEMES[@]}"; do
    check "dashboard-$theme"        dashboard 760 "$theme"
    check "popup-$theme"            popup     940 "$theme"
    check "dashboard-mobile-$theme" dashboard 390 "$theme"
    check "popup-mobile-$theme"     popup     390 "$theme"
done

if (( FAILURES )); then
    echo "T2 render smoke FAILED ($FAILURES view(s))" >&2
    exit 1
fi
echo "T2 render smoke passed (all views)"
