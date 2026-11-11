from pathlib import Path
import logging
import re

from rapidfuzz import fuzz

from ..similarity_scoring import (
    normalize_text,
)
from .manual_playlist_service import (
    AUDIO_EXTENSIONS,
    DOWNLOADS_ROOT,
    LIBRARY_ROOT,
    PLAYLISTS_ROOT,
    find_playlist,
    m3u_entry_to_local_path,
)


logger = logging.getLogger(__name__)

LOSSLESS_EXTENSIONS = {
    ".flac",
    ".wav",
    ".alac",
    ".aiff",
}

MIN_ARTIST_SIMILARITY = 90
MIN_TITLE_SIMILARITY = 92


def format_size(
    size: int,
) -> str:

    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GB"

    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"

    if size >= 1024:
        return f"{size / 1024:.1f} KB"

    return f"{size} B"


def _iter_audio_files():
    for path in sorted(
        LIBRARY_ROOT.rglob("*")
    ):
        if not path.is_file():
            continue

        if path.suffix.casefold() not in AUDIO_EXTENSIONS:
            continue

        # La carpeta de playlists solo
        # contiene ficheros .m3u, pero la
        # excluimos por si acaso.
        if PLAYLISTS_ROOT in path.parents:
            continue

        yield path


def _parse_artist_title(
    path: Path,
):
    # Quitamos numeraciones típicas de
    # descargas: "01 ", "01 - ", "01. "
    stem = re.sub(
        r"^\s*\d{1,3}[\s.\-_]+",
        "",
        path.stem,
    )

    match = re.match(
        r"^(.*?)\s*[-–]\s*(.+)$",
        stem,
    )

    if match:
        return (
            match.group(1).strip(),
            match.group(2).strip(),
        )

    # Sin separador "Artista - Título":
    # usamos la carpeta como artista.
    return (
        path.parent.name,
        stem.strip(),
    )


def _quality_rank(
    path: Path,
) -> tuple:

    # Ordenamos por (lossless primero, luego tamaño).
    # Evitamos leer metadatos de cada fichero: con
    # bibliotecas grandes, hacer stat es lo único
    # que permite un escaneo rápido.
    is_lossless = (
        path.suffix.casefold() in LOSSLESS_EXTENSIONS
    )

    return (
        1 if is_lossless else 0,
        path.stat().st_size,
    )


def _entry_of(
    path: Path,
    is_best: bool,
) -> dict:

    size = path.stat().st_size

    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.casefold().lstrip("."),
        "lossless": path.suffix.casefold() in LOSSLESS_EXTENSIONS,
        "size": size,
        "size_text": format_size(size),
        "is_best": is_best,
    }


def find_duplicates() -> list:
    entries = []

    for path in _iter_audio_files():
        artist, title = _parse_artist_title(path)

        entries.append(
            {
                "path": path,
                "artist": artist,
                "title": title,
            }
        )

    groups = []
    used = set()

    for index, entry in enumerate(entries):
        if index in used:
            continue

        member_indexes = [index]

        artist_key = normalize_text(
            entry["artist"]
        )

        title_key = normalize_text(
            entry["title"]
        )

        for other in range(
            index + 1,
            len(entries),
        ):
            if other in used:
                continue

            other_entry = entries[other]

            artist_score = fuzz.token_sort_ratio(
                artist_key,
                normalize_text(other_entry["artist"]),
            )

            if artist_score < MIN_ARTIST_SIMILARITY:
                continue

            title_score = fuzz.token_set_ratio(
                title_key,
                normalize_text(other_entry["title"]),
            )

            if title_score < MIN_TITLE_SIMILARITY:
                continue

            member_indexes.append(other)
            used.add(other)

        if len(member_indexes) < 2:
            continue

        used.add(index)

        members = sorted(
            (entries[i] for i in member_indexes),
            key=lambda item: _quality_rank(item["path"]),
            reverse=True,
        )

        groups.append(
            {
                "artist": entry["artist"],
                "title": entry["title"],
                "files": [
                    _entry_of(
                        member["path"],
                        position == 0,
                    )
                    for position, member in enumerate(members)
                ],
            }
        )

    return groups


def _is_allowed_path(
    path: Path,
) -> bool:

    if path.suffix.casefold() not in AUDIO_EXTENSIONS:
        return False

    return (
        LIBRARY_ROOT in path.parents
        or DOWNLOADS_ROOT in path.parents
    )


def delete_paths(
    paths: list[str],
) -> list:
    results = []

    for item in paths:
        path = Path(item).resolve()

        if not _is_allowed_path(path):
            results.append(
                {
                    "path": item,
                    "status": "rejected",
                    "error": "fuera de la biblioteca o no es un audio",
                }
            )

            continue

        if not path.is_file():
            results.append(
                {
                    "path": item,
                    "status": "missing",
                }
            )

            continue

        try:
            size = path.stat().st_size

            path.unlink()

            results.append(
                {
                    "path": item,
                    "status": "deleted",
                    "size": size,
                    "size_text": format_size(size),
                }
            )

            logger.warning(
                f"[DUPLICATE DELETED] path={str(path)!r} | size={size}"
            )

        except OSError as error:
            results.append(
                {
                    "path": item,
                    "status": "error",
                    "error": str(error),
                }
            )

    return results


def playlist_orphans_report() -> list:
    reports = []

    for playlist_file in sorted(
        PLAYLISTS_ROOT.iterdir()
    ):
        if not playlist_file.is_file():
            continue

        if playlist_file.suffix.casefold() not in (".m3u", ".m3u8"):
            continue

        try:
            lines = playlist_file.read_text(
                encoding="utf-8"
            ).splitlines()

        except OSError as error:
            reports.append(
                {
                    "name": playlist_file.stem,
                    "filename": playlist_file.name,
                    "error": str(error),
                }
            )

            continue

        total = 0
        missing = 0
        missing_names = []

        for entry in lines:
            if not entry.strip() or entry.strip().startswith("#"):
                continue

            total += 1

            local = m3u_entry_to_local_path(entry)

            if local is None or not local.is_file():
                missing += 1
                missing_names.append(Path(entry).name)

        reports.append(
            {
                "name": playlist_file.stem,
                "filename": playlist_file.name,
                "total": total,
                "missing": missing,
                "missing_names": missing_names[:20],
            }
        )

    return reports


def prune_playlist(
    name: str,
    delete_if_empty: bool = False,
) -> dict:
    playlist_file = find_playlist(name)

    if playlist_file is None:
        return {
            "status": "not_found",
        }

    try:
        lines = playlist_file.read_text(
            encoding="utf-8"
        ).splitlines()

    except OSError as error:
        return {
            "status": "error",
            "error": str(error),
        }

    kept = []
    removed = 0

    for entry in lines:
        if not entry.strip() or entry.strip().startswith("#"):
            kept.append(entry)

            continue

        local = m3u_entry_to_local_path(entry)

        if local is not None and local.is_file():
            kept.append(entry)

        else:
            removed += 1

    if removed == 0:
        return {
            "status": "clean",
            "name": playlist_file.stem,
            "removed": 0,
        }

    remaining_tracks = [
        line
        for line in kept
        if line.strip() and not line.strip().startswith("#")
    ]

    if not remaining_tracks and delete_if_empty:
        playlist_file.unlink()

        logger.warning(
            f"[PLAYLIST DELETED] file={str(playlist_file)!r}"
        )

        return {
            "status": "deleted",
            "name": playlist_file.stem,
            "removed": removed,
        }

    temporary = playlist_file.with_suffix(
        ".m3u.tmp"
    )

    temporary.write_text(
        "\n".join(kept) + "\n",
        encoding="utf-8",
    )

    temporary.replace(playlist_file)

    return {
        "status": "pruned",
        "name": playlist_file.stem,
        "removed": removed,
        "kept": len(remaining_tracks),
    }
