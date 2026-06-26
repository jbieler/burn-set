#!/usr/bin/env python3
"""
DJ Set Cleaner
Liest eine M3U/M3U8-Playlist, konvertiert alle Tracks zu sauberem PCM WAV,
bereinigt Metadaten und Dateinamen, schreibt eine neue M3U.
Metadaten (Title, Artist) werden aus der Quelldatei gelesen und als
ID3v2.3-Tags in die WAV-Ausgabe geschrieben – Burn.app nutzt diese für CD Text.
"""

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

try:
    import mutagen
    from mutagen import File as MutagenFile
    from mutagen.wave import WAVE
    from mutagen.id3 import TIT2, TPE1, TALB, ID3
except ImportError:
    print("ERROR: mutagen fehlt. Starte das Skript über run.sh.")
    sys.exit(1)


FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
TARGET_SR = "44100"
TARGET_DEPTH = "pcm_s16le"
TARGET_CH = "2"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name)
    name = name.replace("–", "-").replace("—", "-")  # en/em-dash
    name = re.sub(r'[/\\:*?"<>|]', "_", name)
    name = re.sub(r" {2,}", " ", name)
    return name.strip()[:100]


def sanitize_tag(value: str) -> str:
    if not value:
        return ""
    value = value.replace("\x00", "")
    value = unicodedata.normalize("NFC", value)
    return value.strip()


def probe(path: Path) -> dict:
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout)
    except Exception:
        return {}


def needs_conversion(path: Path) -> bool:
    """True wenn die Datei kein sauberes PCM WAV 44.1 kHz 16-bit ist."""
    if path.suffix.lower() != ".wav":
        return True
    info = probe(path)
    for s in info.get("streams", []):
        if s.get("codec_type") == "audio":
            if s.get("codec_name") != "pcm_s16le":
                return True
            if str(s.get("sample_rate", "")) != TARGET_SR:
                return True
            return False
    return True


# ---------------------------------------------------------------------------
# Metadaten aus Quelldatei lesen
# ---------------------------------------------------------------------------

def read_source_tags(path: Path) -> dict:
    """
    Liest Title, Artist, Album aus der Quelldatei.
    Unterstützt MP3 (ID3), M4A (MP4-Tags), WAV (ID3 in WAV).
    Gibt dict mit 'title', 'artist', 'album' zurück (leer wenn nicht vorhanden).
    """
    tags = {"title": "", "artist": "", "album": ""}
    try:
        f = MutagenFile(str(path), easy=True)
        if f is None:
            return tags
        t = f.tags
        if t is None:
            return tags

        def get(key):
            v = t.get(key)
            if not v:
                return ""
            val = v[0] if isinstance(v, list) else str(v)
            return sanitize_tag(str(val))

        tags["title"] = get("title")
        tags["artist"] = get("artist")
        tags["album"] = get("album")
    except Exception:
        pass
    return tags


def merge_metadata(source_tags: dict, extinf_title: str) -> dict:
    """
    Kombiniert Quelldatei-Tags mit EXTINF-Fallback.
    Quelldatei hat Vorrang; EXTINF wird nur genutzt wenn Tags leer sind.
    """
    title = source_tags.get("title", "")
    artist = source_tags.get("artist", "")
    album = source_tags.get("album", "")

    if not title or not artist:
        # Fallback: "Artist - Title" aus EXTINF parsen
        if " - " in extinf_title:
            fb_artist, fb_title = extinf_title.split(" - ", 1)
        else:
            fb_artist, fb_title = "", extinf_title
        title = title or sanitize_tag(fb_title)
        artist = artist or sanitize_tag(fb_artist)

    return {"title": title, "artist": artist, "album": album}


# ---------------------------------------------------------------------------
# Konvertierung & Tag-Schreiben
# ---------------------------------------------------------------------------

def convert_to_wav(src: Path, dst: Path) -> bool:
    """Konvertiert zu PCM WAV, entfernt alle Original-Tags."""
    cmd = [
        FFMPEG, "-y", "-i", str(src),
        "-vn",
        "-map_metadata", "-1",  # alle Original-Tags entfernen
        "-acodec", TARGET_DEPTH,
        "-ar", TARGET_SR,
        "-ac", TARGET_CH,
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return dst.exists() and dst.stat().st_size > 0


def write_wav_tags(path: Path, meta: dict) -> None:
    """
    Schreibt ID3v2.3-Tags in die WAV-Datei.
    Burn.app liest diese Tags und überträgt sie als CD Text auf die Disc.
    encoding=3 = UTF-8
    """
    try:
        audio = WAVE(str(path))
        if audio.tags is None:
            audio.add_tags()
        t = audio.tags
        title = sanitize_tag(meta.get("title", "")) or "Unknown"
        artist = sanitize_tag(meta.get("artist", "")) or "Unknown"
        album = sanitize_tag(meta.get("album", ""))

        t["TIT2"] = TIT2(encoding=3, text=title)
        t["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            t["TALB"] = TALB(encoding=3, text=album)
        audio.save()
    except Exception:
        # Fallback: alle Tags per ffmpeg strippen – lieber keine als kaputte
        tmp = path.with_suffix(".tmp.wav")
        cmd = [FFMPEG, "-y", "-i", str(path), "-map_metadata", "-1",
               "-acodec", "copy", str(tmp)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
            if tmp.exists():
                tmp.replace(path)
        except Exception:
            pass


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
                })
                current = None
    return tracks


def write_m3u(tracks: list, out: Path) -> None:
    with open(out, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for t in tracks:
            artist = t.get("meta", {}).get("artist", "")
            title = t.get("meta", {}).get("title", "")
            label = f"{artist} - {title}" if artist and title else t["extinf_title"]
            f.write(f"#EXTINF:{t['duration']},{label}\n")
            f.write((t["out_path"] or t["src_path"]) + "\n")


def write_cue(tracks: list, out: Path, disc_title: str = "") -> None:
    """
    Schreibt ein CUE-Sheet mit CD Text.
    Jede WAV-Datei ist ein eigener FILE-Eintrag (noncompliant split-file CUE),
    was cdrecord -dao korrekt verarbeitet.
    """
    with open(out, "w", encoding="utf-8") as f:
        if disc_title:
            f.write(f'TITLE "{sanitize_tag(disc_title)}"\n')
        f.write('REM COMMENT "Created by DJ Set Cleaner"\n')
        for i, t in enumerate(tracks, 1):
            wav = Path(t["out_path"]).name
            meta = t.get("meta", {})
            title = sanitize_tag(meta.get("title", "")) or t["extinf_title"]
            artist = sanitize_tag(meta.get("artist", ""))
            f.write(f'FILE "{wav}" WAVE\n')
            f.write(f"  TRACK {i:02d} AUDIO\n")
            f.write(f'    TITLE "{title}"\n')
            if artist:
                f.write(f'    PERFORMER "{artist}"\n')
            f.write(f"    INDEX 01 00:00:00\n")


def total_duration_seconds(tracks: list) -> int:
    total = 0
    for t in tracks:
        try:
            total += int(t["duration"])
        except (ValueError, TypeError):
            pass
    return total


def split_playlist(tracks: list) -> tuple:
    """Verteilt Tracks abwechselnd auf Playlist A (ungerade) und B (gerade)."""
    a = [t for i, t in enumerate(tracks) if i % 2 == 0]
    b = [t for i, t in enumerate(tracks) if i % 2 == 1]
    return a, b


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Verwendung: python3 djset_cleaner.py <playlist.m3u> [ausgabe_ordner]")
        sys.exit(1)

    playlist_path = Path(sys.argv[1])
    if not playlist_path.exists():
        print(f"ERROR: Playlist nicht gefunden: {playlist_path}")
        sys.exit(1)

    output_dir = (
        Path(sys.argv[2]).expanduser()
        if len(sys.argv) > 2
        else Path.home() / "burn-set" / "output"
    )
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

        # Metadaten: Quelldatei hat Vorrang, EXTINF als Fallback
        source_tags = read_source_tags(src)
        meta = merge_metadata(source_tags, track["extinf_title"])
        track["meta"] = meta

        # Ausgabedateiname aus bereinigten Tags
        name_base = f"{i:02d} - {meta['artist']} - {meta['title']}" if meta["artist"] else f"{i:02d} - {meta['title']}"
        clean_stem = sanitize_filename(name_base)
        out_path = output_dir / (clean_stem + ".wav")

        tag_source = "Datei-Tags" if source_tags.get("title") else "EXTINF"
        display = f"{meta['artist']} - {meta['title']}" if meta["artist"] else meta["title"]

        try:
            if needs_conversion(src):
                ok = convert_to_wav(src, out_path)
                if not ok:
                    raise RuntimeError("ffmpeg Konvertierung fehlgeschlagen")
                write_wav_tags(out_path, meta)
                print(f"{prefix} [CONVERT]  {display[:col]}")
                print(f"            Quelle: {src.suffix.upper()[1:]} → WAV  |  Tags: {tag_source}")
            else:
                shutil.copy2(src, out_path)
                write_wav_tags(out_path, meta)
                print(f"{prefix} [OK]       {display[:col]}")
                print(f"            Tags: {tag_source}")

            track["out_path"] = str(out_path)

        except Exception as e:
            print(f"{prefix} [FEHLER]   {src.name} → {e}")
            errors.append(str(src))

    # Ausgabe-Playlist(en) schreiben
    stem = sanitize_filename(playlist_path.stem)
    burn_set_dir = Path.home() / "burn-set"

    completed = [t for t in tracks if t.get("out_path")]
    secs = total_duration_seconds(completed)
    LIMIT = 80 * 60  # 80 Minuten in Sekunden

    print(f"\n{'─' * 55}")
    print(f"Fertig: {total - len(errors)}/{total} Tracks bereinigt")
    print(f"Gesamtlänge: {secs // 60}:{secs % 60:02d} min")

    disc_title = playlist_path.stem

    if secs > LIMIT:
        tracks_a, tracks_b = split_playlist(completed)
        secs_a = total_duration_seconds(tracks_a)
        secs_b = total_duration_seconds(tracks_b)

        out_m3u_a = burn_set_dir / (stem + "_A.m3u")
        out_m3u_b = burn_set_dir / (stem + "_B.m3u")
        out_cue_a = burn_set_dir / (stem + "_A.cue")
        out_cue_b = burn_set_dir / (stem + "_B.cue")

        write_m3u(tracks_a, out_m3u_a)
        write_m3u(tracks_b, out_m3u_b)
        write_cue(tracks_a, out_cue_a, disc_title=disc_title + " (A)")
        write_cue(tracks_b, out_cue_b, disc_title=disc_title + " (B)")

        print(f"Playlist > 80 min → aufgeteilt in A und B (abwechselnd):")
        print(f"  Playlist A: {len(tracks_a)} Tracks, {secs_a // 60}:{secs_a % 60:02d} min")
        print(f"    M3U: {out_m3u_a}")
        print(f"    CUE: {out_cue_a}")
        print(f"  Playlist B: {len(tracks_b)} Tracks, {secs_b // 60}:{secs_b % 60:02d} min")
        print(f"    M3U: {out_m3u_b}")
        print(f"    CUE: {out_cue_b}")
        print()
        print(f"Brennen (Disc A):  ./burn.sh \"{out_cue_a}\"")
        print(f"Brennen (Disc B):  ./burn.sh \"{out_cue_b}\"")
    else:
        out_playlist = burn_set_dir / (stem + "_clean.m3u")
        out_cue     = burn_set_dir / (stem + ".cue")
        write_m3u(completed, out_playlist)
        write_cue(completed, out_cue, disc_title=disc_title)
        print(f"M3U: {out_playlist}")
        print(f"CUE: {out_cue}")
        print()
        print(f"Brennen:  ./burn.sh \"{out_cue}\"")

    if errors:
        print(f"\nFehler ({len(errors)}):")
        for e in errors:
            print(f"  • {e}")


if __name__ == "__main__":
    main()
