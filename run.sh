#!/bin/bash
# DJ Set Cleaner – Startskript
# Verwendung: ./run.sh playlist.m3u [ausgabe_ordner]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtuelle Umgebung fehlt. Einmalige Installation..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install mutagen -q
fi

# Suche python-Binary im venv (python3, python3.x, python)
PYTHON=""
for candidate in "$VENV_DIR/bin/python3" "$VENV_DIR/bin/python" "$VENV_DIR/bin/python"3.*; do
    if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Kein Python-Binary in $VENV_DIR/bin gefunden."
    echo "       Lösche den .venv-Ordner und führe install.sh erneut aus."
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/djset_cleaner.py" "$@"
