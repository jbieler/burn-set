#!/bin/bash
# DJ Set Cleaner – Brennskript
# Verwendung: ./burn.sh <playlist.cue> [--simulate]
#
# Voraussetzung: cdrtools (brew install cdrtools)

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

# Optisches Laufwerk über drutil suchen (zuverlässiger als cdrecord -scanbus auf macOS)
echo "Suche optisches Laufwerk..."
DISK_NODE="$(drutil status 2>/dev/null | awk '/Name:/{print $NF; exit}')"

if [ -z "$DISK_NODE" ]; then
    # Fallback: system_profiler
    DISK_NODE="$(system_profiler SPDiscBurningDataType 2>/dev/null \
        | awk '/BSD Name:/{print $NF; exit}')"
fi

if [ -z "$DISK_NODE" ]; then
    echo "ERROR: Kein optisches Laufwerk gefunden."
    echo "       Stelle sicher, dass eine leere CD eingelegt ist."
    exit 1
fi

# cdrecord braucht das raw device (rdisk statt disk)
DEVICE="/dev/r${DISK_NODE#/dev/}"

echo "Laufwerk: $DEVICE"
echo "CUE:      $CUE_FILE"
echo ""

# WAV-Dateien aus CUE prüfen
echo "Prüfe Tracks..."
MISSING=0
while IFS= read -r line; do
    if [[ "$line" =~ ^FILE\ \"(.+)\"\ WAVE ]]; then
        WAV="${BASH_REMATCH[1]}"
        # Absoluten oder relativen Pfad korrekt auflösen
        if [[ "$WAV" = /* ]]; then
            FULL="$WAV"
        else
            FULL="$CUE_DIR/$WAV"
        fi
        if [ ! -f "$FULL" ]; then
            echo "  FEHLER: $FULL nicht gefunden"
            MISSING=$((MISSING + 1))
        else
            echo "  OK: $(basename "$WAV")"
        fi
    fi
done < "$CUE_FILE"

if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "ERROR: $MISSING WAV-Datei(en) fehlen. Abbruch."
    exit 1
fi

echo ""

# cdrecord braucht root für Gerätezugriff und Echtzeit-Priorität
cd "$CUE_DIR"

if [ "$SIMULATE" -eq 1 ]; then
    echo "Simulation (kein echter Brennvorgang):"
    sudo "$CDRECORD" -v -dao -text -dummy "dev=$DEVICE" "cuefile=$(basename "$CUE_FILE")"
else
    echo "Starte Brennvorgang – CD nicht entnehmen!"
    echo ""
    sudo "$CDRECORD" -v -dao -text "dev=$DEVICE" "cuefile=$(basename "$CUE_FILE")"
fi
