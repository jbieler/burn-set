#!/usr/bin/env python3
"""
DJ Set Cleaner
Bereitet DJ-Sets aus Rekordbox für das Brennen mit Burn.app vor.

Liest eine M3U/M3U8-Playlist und erzeugt bereinigte Kopien der Tracks in einem
Ausgabeordner – ohne Konvertierung, das Originalformat (MP3/M4A/...) bleibt erhalten.
Bereinigt werden Metadaten (Title, Artist) und Dateinamen.

Ziel: Burn.app stürzt nicht mehr ab (Crash durch leere/ungültige Tag-Felder)
und zeigt CD-Text korrekt an.

Die Originaldateien werden NIEMALS verändert – es wird ausschließlich auf Kopien
gearbeitet.
"""

import re
import shutil
import sys
import unicodedata
from pathlib import Path

try:
    from mutagen import File as MutagenFile
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1
except ImportError:
    print("ERROR: mutagen fehlt. Starte das Skript über run.sh.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Bereinigung
# ---------------------------------------------------------------------------

# Steuerzeichen (ohne Tab/Newline, die wir ohnehin entfernen) und Null-Bytes
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_tag(value: str) -> str:
    """Bereinigt einen Metadaten-Wert: Null-Bytes/Steuerzeichen raus,
    Unicode normalisieren, Whitespace zusammenfassen."""
    if not value:
        return ""
    value = unicodedata.normalize("NFC", str(value))
    value = _CONTROL_CHARS.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()[:250]


def sanitize_filename(name: str) -> str:
    """Bereinigt einen Dateinamen (ohne Endung)."""
    name = unicodedata.normalize("NFC", name)
    name = name.replace("–", "-").replace("—", "-")   # en/em-dash
    name = _CONTROL_CHARS.sub("", name)
    name = re.sub(r'[/\\:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()[:100]


# ---------------------------------------------------------------------------
# Metadaten lesen
# ---------------------------------------------------------------------------

def read_source_tags(path: Path) -> dict:
    """Liest Title und Artist aus der Quelldatei (MP3/M4A/...)."""
    tags = {"title": "", "artist": ""}
    try:
        f = MutagenFile(str(path), easy=True)
        if f is None or f.tags is None:
            return tags

        def get(key):
            v = f.tags.get(key)
            if not v:
                return ""
            val = v[0] if isinstance(v, list) else v
            return sanitize_tag(str(val))

        tags["title"] = get("title")
        tags["artist"] = get("artist")
    except Exception:
        pass
    return tags


def merge_metadata(source_tags: dict, extinf_title: str) -> dict:
    """Quelldatei-Tags haben Vorrang; EXTINF (Rekordbox) als Fallback."""
    title = source_tags.get("title", "")
    artist = source_tags.get("artist", "")

    if not title or not artist:
        if " - " in extinf_title:
            fb_artist, fb_title = extinf_title.split(" - ", 1)
        else:
            fb_artist, fb_title = "", extinf_title
        title = title or sanitize_tag(fb_title)
        artist = artist or sanitize_tag(fb_artist)

    # Pflichtfelder dürfen nie leer sein – das war die Crash-Ursache in Burn.app
    return {
        "title": title or "Unknown",
        "artist": artist or "Unknown",
    }


# ---------------------------------------------------------------------------
# Metadaten in die Kopie schreiben
# ---------------------------------------------------------------------------

def clean_tags(path: Path, meta: dict) -> None:
    """
    Schreibt ausschließlich saubere Title/Artist-Tags in die Kopie.
    Alle vorhandenen Tags werden zuvor entfernt, damit kein beschädigtes
    Restfeld (z.B. leeres Album, kaputtes Encoding) Burn.app zum Absturz bringt.
    """
    title = sanitize_tag(meta["title"]) or "Unknown"
    artist = sanitize_tag(meta["artist"]) or "Unknown"

    if path.suffix.lower() == ".mp3":
        # MP3: alle Tags entfernen, dann sauberes ID3v2.3 schreiben
        try:
            audio = MP3(str(path))
            if audio.tags is not None:
                audio.delete()
            audio.tags = ID3()
            audio.tags.add(TIT2(encoding=3, text=title))
            audio.tags.add(TPE1(encoding=3, text=artist))
            audio.save(v2_version=3)
            return
        except Exception as e:
            print(f"            Warnung: ID3-Tags fehlgeschlagen ({e}).")
            return

    # Andere Formate (M4A etc.): generisch über mutagen easy
    try:
        audio = MutagenFile(str(path), easy=True)
        if audio is None:
            print("            Warnung: Format für Tag-Schreiben nicht erkannt.")
            return
        try:
            audio.delete()
        except Exception:
            pass
        if audio.tags is None:
            audio.add_tags()
        audio["title"] = title
        audio["artist"] = artist
        audio.save()
    except Exception as e:
        print(f"            Warnung: Tags konnten nicht geschrieben werden ({e}).")


# ---------------------------------------------------------------------------
# M3U Parser / Writer
# ---------------------------------------------------------------------------

def parse_m3u(playlist: Path) -> list:
    tracks = []
    current = None
    with open(playlist, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if line.startswith("#EXTINF:"):
                rest = line[8:]
                comma = rest.find(",")
                if comma >= 0:
                    duration = rest[:comma].strip()
                    title = rest[comma + 1:].strip()
                else:
                    duration = rest.strip()
                    title = ""
                current = (duration, title)
            elif line and not line.startswith("#"):
                duration, title = current if current else ("0", "")
                tracks.append({
                    "duration": duration,
                    "extinf_title": title,
                    "src_path": line.strip(),
                    "out_path": None,
                    "meta": None,
                })
                current = None
    return tracks


def write_m3u(tracks: list, out: Path) -> None:
    with open(out, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t in tracks:
            meta = t.get("meta") or {}
            artist = meta.get("artist", "")
            title = meta.get("title", "")
            label = f"{artist} - {title}" if artist and title else t["extinf_title"]
            f.write(f"#EXTINF:{t['duration']},{label}\n")
            f.write((t["out_path"] or t["src_path"]) + "\n")


def total_duration_seconds(tracks: list) -> int:
    total = 0
    for t in tracks:
        try:
            total += int(t["duration"])
        except (ValueError, TypeError):
            pass
    return total


def split_playlist(tracks: list) -> tuple:
    """Verteilt Tracks abwechselnd auf Playlist A (1,3,5…) und B (2,4,6…)."""
    a = [t for i, t in enumerate(tracks) if i % 2 == 0]
    b = [t for i, t in enumerate(tracks) if i % 2 == 1]
    return a, b


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Verwendung: python3 djset_cleaner.py <playlist.m3u>")
        sys.exit(1)

    playlist_path = Path(sys.argv[1])
    if not playlist_path.exists():
        print(f"ERROR: Playlist nicht gefunden: {playlist_path}")
        sys.exit(1)

    stem = sanitize_filename(playlist_path.stem)
    disc_dir = Path.cwd() / stem
    output_dir = disc_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    tracks = parse_m3u(playlist_path)
    total = len(tracks)
    print(f"Playlist: {playlist_path.name}")
    print(f"Tracks:   {total}")
    print(f"Output:   {output_dir}\n")

    col = 45
    errors = []

    for i, track in enumerate(tracks, 1):
        src = Path(track["src_path"])
        prefix = f"[{i:02d}/{total}]"

        if not src.exists():
            print(f"{prefix} [FEHLER]   Datei nicht gefunden:")
            print(f"            {src}")
            errors.append(str(src))
            continue

        source_tags = read_source_tags(src)
        meta = merge_metadata(source_tags, track["extinf_title"])
        track["meta"] = meta

        # Dateiname: Nummer + Artist - Title, Originalendung beibehalten
        name_base = f"{i:02d} - {meta['artist']} - {meta['title']}"
        clean_stem = sanitize_filename(name_base)
        out_path = output_dir / (clean_stem + src.suffix.lower())

        tag_source = "Datei-Tags" if source_tags.get("title") else "EXTINF"
        display = f"{meta['artist']} - {meta['title']}"

        try:
            # Original unverändert kopieren ...
            shutil.copy2(src, out_path)
            # ... dann NUR die Kopie bereinigen
            clean_tags(out_path, meta)
            track["out_path"] = str(out_path)
            print(f"{prefix} [OK]       {display[:col]}")
            print(f"            {src.suffix.upper()[1:]}  |  Tags: {tag_source}")
        except Exception as e:
            print(f"{prefix} [FEHLER]   {src.name} → {e}")
            errors.append(str(src))

    completed = [t for t in tracks if t.get("out_path")]
    secs = total_duration_seconds(completed)
    LIMIT = 80 * 60

    print(f"\n{'─' * 55}")
    print(f"Fertig: {total - len(errors)}/{total} Tracks bereinigt")
    print(f"Gesamtlänge: {secs // 60}:{secs % 60:02d} min")

    if secs > LIMIT:
        tracks_a, tracks_b = split_playlist(completed)
        secs_a = total_duration_seconds(tracks_a)
        secs_b = total_duration_seconds(tracks_b)

        write_m3u(tracks_a, disc_dir / (stem + "_A.m3u"))
        write_m3u(tracks_b, disc_dir / (stem + "_B.m3u"))

        print(f"Playlist > 80 min → aufgeteilt in A und B (abwechselnd):")
        print(f"  Disc A: {len(tracks_a)} Tracks, {secs_a // 60}:{secs_a % 60:02d} min → {stem}_A.m3u")
        print(f"  Disc B: {len(tracks_b)} Tracks, {secs_b // 60}:{secs_b % 60:02d} min → {stem}_B.m3u")
    else:
        write_m3u(completed, disc_dir / (stem + ".m3u"))
        print(f"Playlist: {stem}.m3u")

    print(f"Ordner:   {disc_dir}")

    if errors:
        print(f"\nFehler ({len(errors)}):")
        for e in errors:
            print(f"  • {e}")

    print()
    print("Nächster Schritt in Burn.app:")
    print("  1. Neue Audio-CD anlegen")
    print(f"  2. Dateien aus '{output_dir}' per Drag & Drop hineinziehen")
    print("  3. Reihenfolge stimmt durch die Nummerierung automatisch")
    print("  4. Brennen")


if __name__ == "__main__":
    main()
