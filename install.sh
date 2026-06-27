#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "DJ Set Cleaner – Installation"
echo "────────────────────────────────"

# Python 3
if ! command -v python3 &>/dev/null; then
    if command -v brew &>/dev/null; then
        echo "→ Installiere python..."
        brew install python
    else
        echo "ERROR: python3 nicht gefunden und Homebrew nicht installiert."
        echo "       Installiere Python: https://www.python.org oder https://brew.sh"
        exit 1
    fi
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

echo ""
echo "Installation abgeschlossen."
echo ""
echo "Verwendung:"
echo "  cd $SCRIPT_DIR"
echo "  ./run.sh \"/Pfad/zur/playlist.m3u\""
