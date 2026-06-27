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

# cdrecord auf macOS braucht IOKit-Gerätenamen, nicht /dev/diskX
# Prüfe welcher Name verfügbar ist
echo "Suche optisches Laufwerk..."
DEVICE=""
for candidate in IOCompactDiscServices IODVDServices IODVDServices/1; do
    if sudo "$CDRECORD" -inq "dev=$candidate" &>/dev/null; then
        DEVICE="$candidate"
        break
    fi
done

if [ -z "$DEVICE" ]; then
    echo "ERROR: Kein brennfähiges Laufwerk gefunden."
    echo "       Stelle sicher, dass eine leere CD eingelegt ist."
    echo "       Verfügbare Geräte: sudo cdrecord -scanbus"
    exit 1
fi

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

# Gesamtspieldauer prüfen (80-Minuten-CD = 4800 Sekunden)
CD_MAX_SECS=4800
TOTAL_SECS=0
FFPROBE_BIN="$(command -v ffprobe 2>/dev/null)"

if [ -z "$FFPROBE_BIN" ]; then
    echo "Warnung: ffprobe nicht gefunden, Dauerprüfung übersprungen."
else
    while IFS= read -r line; do
        if [[ "$line" =~ ^FILE\ \"(.+)\"\ WAVE ]]; then
            WAV="${BASH_REMATCH[1]}"
            if [[ "$WAV" = /* ]]; then
                FULL="$WAV"
            else
                FULL="$CUE_DIR/$WAV"
            fi
            DUR=$("$FFPROBE_BIN" -v quiet -show_entries format=duration \
                -of default=noprint_wrappers=1:nokey=1 "$FULL" 2>/dev/null | cut -d. -f1)
            TOTAL_SECS=$((TOTAL_SECS + ${DUR:-0}))
        fi
    done < "$CUE_FILE"

    CD_OVERBURN_MAX_SECS=5400  # 90 Minuten – absolutes Limit auch mit Overburn

    TOTAL_MIN=$((TOTAL_SECS / 60))
    TOTAL_SEC=$((TOTAL_SECS % 60))
    echo ""
    echo "Gesamtspieldauer: ${TOTAL_MIN}:$(printf '%02d' $TOTAL_SEC) min (Standard: 80:00, Overburn-Limit: 90:00)"

    if [ "$TOTAL_SECS" -gt "$CD_OVERBURN_MAX_SECS" ]; then
        OVER=$((TOTAL_SECS - CD_OVERBURN_MAX_SECS))
        OVER_MIN=$((OVER / 60))
        OVER_SEC=$((OVER % 60))
        echo "ERROR: Playlist ist ${OVER_MIN}:$(printf '%02d' $OVER_SEC) min zu lang selbst für Overburn. Abbruch."
        echo "       Teile die Playlist in kleinere Sets auf."
        exit 1
    elif [ "$TOTAL_SECS" -gt "$CD_MAX_SECS" ]; then
        OVER=$((TOTAL_SECS - CD_MAX_SECS))
        OVER_MIN=$((OVER / 60))
        OVER_SEC=$((OVER % 60))
        echo "Warnung: Playlist ist ${OVER_MIN}:$(printf '%02d' $OVER_SEC) min über 80 min – wird mit Overburn versucht."
    fi
fi

FFMPEG_BIN="$(command -v ffmpeg 2>/dev/null)"
SPEED=8

# Tag-freie WAV-Kopien erstellen
# ID3-Chunks in WAV-Dateien verschieben cdrecords Sektorberechnung,
# wodurch nur Track 1 auf dem CD-Player abspielbar ist.
# Lösung: vor dem Brennen neu encoden ohne Metadaten.
BURN_TMP="$(mktemp -d)"
BURN_CUE="$BURN_TMP/$(basename "$CUE_FILE")"

cleanup() {
    rm -rf "$BURN_TMP"
}
trap cleanup EXIT

echo "Erstelle tag-freie WAV-Kopien..."

if [ -z "$FFMPEG_BIN" ]; then
    echo "ERROR: ffmpeg nicht gefunden."
    exit 1
fi

while IFS= read -r line; do
    if [[ "$line" =~ ^FILE\ \"(.+)\"\ WAVE ]]; then
        WAV="${BASH_REMATCH[1]}"
        if [[ "$WAV" = /* ]]; then
            ORIG="$WAV"
        else
            ORIG="$CUE_DIR/$WAV"
        fi
        CLEAN="$BURN_TMP/$(basename "$WAV")"
        # Neu encoden (nicht nur kopieren) damit der ID3-Chunk garantiert entfernt wird
        "$FFMPEG_BIN" -y -i "$ORIG" \
            -map_metadata -1 \
            -acodec pcm_s16le \
            -ar 44100 -ac 2 \
            "$CLEAN" 2>/dev/null
        echo "  OK: $(basename "$WAV")"
        echo "FILE \"$CLEAN\" WAVE" >> "$BURN_CUE"
    else
        echo "$line" >> "$BURN_CUE"
    fi
done < "$CUE_FILE"

echo ""

cd "$BURN_TMP"

if [ "$SIMULATE" -eq 1 ]; then
    echo "Simulation (kein echter Brennvorgang):"
    sudo "$CDRECORD" -v -dao -text -pad -overburn -dummy "speed=$SPEED" "dev=$DEVICE" "cuefile=$(basename "$BURN_CUE")"
else
    echo "Starte Brennvorgang mit ${SPEED}x – CD nicht entnehmen!"
    echo ""
    sudo "$CDRECORD" -v -dao -text -pad -overburn "speed=$SPEED" "dev=$DEVICE" "cuefile=$(basename "$BURN_CUE")"
fi
