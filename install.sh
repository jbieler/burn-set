#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "DJ Set Cleaner – Installation"
echo "────────────────────────────────"

# Homebrew
if ! command -v brew &>/dev/null; then
    echo "ERROR: Homebrew ist nicht installiert."
    echo "       Installiere es zuerst: https://brew.sh"
    exit 1
fi

# ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "→ Installiere ffmpeg..."
    brew install ffmpeg
else
    echo "✓ ffmpeg vorhanden ($(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3))"
fi

# cdrtools (cdrecord zum Brennen)
if ! command -v cdrecord &>/dev/null; then
    echo "→ Installiere cdrtools (cdrecord)..."
    brew install cdrtools
else
    echo "✓ cdrecord vorhanden"
fi

# Python 3
if ! command -v python3 &>/dev/null; then
    echo "→ Installiere python..."
    brew install python
else
    echo "✓ python3 vorhanden ($(python3 --version))"
fi

# Virtuelle Umgebung + mutagen
echo "→ Richte Python-Umgebung ein..."
python3 -m venv "$SCRIPT_DIR/.venv"

# Suche pip im venv (pip3, pip, pip3.x)
VENV_PIP=""
for candidate in "$SCRIPT_DIR/.venv/bin/pip3" "$SCRIPT_DIR/.venv/bin/pip" "$SCRIPT_DIR/.venv/bin/pip"3.*; do
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        VENV_PIP="$candidate"
        break
    fi
done

if [ -z "$VENV_PIP" ]; then
    echo "ERROR: Kein pip im venv gefunden. Prüfe deine Python-Installation."
    exit 1
fi

"$VENV_PIP" install --upgrade pip -q
"$VENV_PIP" install mutagen -q
echo "✓ mutagen installiert"

# Skript ausführbar machen
chmod +x "$SCRIPT_DIR/run.sh"

# ffmpeg-Pfad in djset_cleaner.py anpassen (falls nicht in /opt/homebrew)
FFMPEG_PATH="$(command -v ffmpeg)"
FFPROBE_PATH="$(command -v ffprobe)"
sed -i '' \
    "s|FFMPEG = \".*\"|FFMPEG = \"$FFMPEG_PATH\"|" \
    "$SCRIPT_DIR/djset_cleaner.py"
sed -i '' \
    "s|FFPROBE = \".*\"|FFPROBE = \"$FFPROBE_PATH\"|" \
    "$SCRIPT_DIR/djset_cleaner.py"

echo ""
echo "Installation abgeschlossen."
echo ""
echo "Verwendung:"
echo "  cd $SCRIPT_DIR"
echo "  ./run.sh \"/Pfad/zur/playlist.m3u\""
