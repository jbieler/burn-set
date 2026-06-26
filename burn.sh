#!/bin/bash
# DJ Set Cleaner – Brennskript
# Verwendung: ./burn.sh <playlist.cue> [--simulate]
#
# Voraussetzung: cdrtools (brew install cdrtools)
# Das CUE-Sheet und die WAV-Dateien müssen im selben Ordner liegen.

set -e

CDRECORD="$(command -v cdrecord 2>/dev/null || echo "")"

if [ -z "$CDRECORD" ]; then
    echo "ERROR: cdrecord nicht gefunden."
    echo "       Installiere es mit:  brew install cdrtools"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Verwendung: ./burn.sh <playlist.cue> [--simulate]"
    exit 1
fi

CUE_FILE="$(realpath "$1")"
CUE_DIR="$(dirname "$CUE_FILE")"

if [ ! -f "$CUE_FILE" ]; then
    echo "ERROR: CUE-Datei nicht gefunden: $CUE_FILE"
    exit 1
fi

SIMULATE=0
if [ "$2" = "--simulate" ]; then
    SIMULATE=1
    echo "*** SIMULATIONSMODUS – es wird nichts gebrannt ***"
fi

# Optisches Laufwerk suchen
echo "Suche optisches Laufwerk..."
DEVICE="$($CDRECORD -scanbus 2>/dev/null | awk '/CD|DVD|Blu/ {print $1; exit}')"

if [ -z "$DEVICE" ]; then
    # Fallback: erstes optisches Gerät über system_profiler
    DEV_NODE="$(system_profiler SPDiscBurningDataType 2>/dev/null \
        | awk '/Interconnect:/{found=1} found && /BSD Name:/{print $NF; exit}')"
    if [ -n "$DEV_NODE" ]; then
        DEVICE="/dev/$DEV_NODE"
    fi
fi

if [ -z "$DEVICE" ]; then
    echo "ERROR: Kein optisches Laufwerk gefunden."
    echo "       Stelle sicher, dass eine leere CD eingelegt ist."
    exit 1
fi

echo "Laufwerk: $DEVICE"
echo "CUE:      $CUE_FILE"
echo ""

# WAV-Dateien aus CUE lesen und prüfen
echo "Prüfe Tracks..."
MISSING=0
while IFS= read -r line; do
    if [[ "$line" =~ ^FILE\ \"(.+)\"\ WAVE ]]; then
        WAV="${BASH_REMATCH[1]}"
        FULL="$CUE_DIR/$WAV"
        if [ ! -f "$FULL" ]; then
            echo "  FEHLER: $WAV nicht gefunden"
            MISSING=$((MISSING + 1))
        else
            echo "  OK: $WAV"
        fi
    fi
done < "$CUE_FILE"

if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "ERROR: $MISSING WAV-Datei(en) fehlen. Abbruch."
    exit 1
fi

echo ""

if [ "$SIMULATE" -eq 1 ]; then
    echo "Simulation:"
    "$CDRECORD" -v -dao -text -dummy "dev=$DEVICE" "cuefile=$CUE_FILE"
else
    echo "Starte Brennvorgang – CD nicht entnehmen!"
    echo ""
    # In das CUE-Verzeichnis wechseln, da cdrecord relative Pfade im CUE erwartet
    cd "$CUE_DIR"
    "$CDRECORD" -v -dao -text "dev=$DEVICE" "cuefile=$(basename "$CUE_FILE")"
fi
