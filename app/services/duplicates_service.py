from pathlib import Path
import logging
import re

import mutagen
from rapidfuzz import fuzz

from ..similarity_scoring import (
    normalize_text,
)
from .manual_playlist_service import (
    AUDIO_EXTENSIONS,
    DOWNLOADS_ROOT,
    LIBRARY_ROOT,
    m3u_entry_to_local_path,
)


logger = logging.getLogger(__name__)

LOSSLESS_EXTENSIONS = {
    ".flac",
    ".wav",
    ".alac",
    ".aiff",
}

M3U_EXTENSIONS = {
    ".m3u",
    ".m3u8",
}

MIN_ARTIST_SIMILARITY = 85
MIN_TITLE_SIMILARITY = 88


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


def _is_playlists_dir(
    path: Path,
) -> bool:

    # Cualquier carpeta llamada PLAYLISTS dentro
    # de la biblioteca es zona de .m3u, no de
    # audio.
    return any(
        parent.name.casefold() == "playlists"
        for parent in path.parents
    )


def _iter_audio_files():
    for path in sorted(
        LIBRARY_ROOT.rglob("*")
    ):
        if not path.is_file():
            continue

        if path.suffix.casefold() not in AUDIO_EXTENSIONS:
            continue

        if _is_playlists_dir(path):
            continue

        yield path


def _tags_of(
    path: Path,
):
    try:
        audio = mutagen.File(
            str(path),
            easy=True,
        )

        if audio is None or audio.info is None:
            return None, None

        artist = audio.get("artist")
        title = audio.get("title")

        artist = artist[0].strip() if artist else None
        title = title[0].strip() if title else None

        return artist, title

    except Exception:
        return None, None


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


def _identify(
    path: Path,
):
    # La verdad está en los tags ID3; el
    # nombre del fichero es el plan B.
    artist, title = _tags_of(path)

    if artist and title:
        return artist, title

    fallback_artist, fallback_title = (
        _parse_artist_title(path)
    )

    return (
        artist or fallback_artist,
        title or fallback_title,
    )


def _quality_rank(
    path: Path,
) -> tuple:

    # Ordenamos por (lossless primero, luego tamaño).
    # Es lo que permite un escaneo rápido sin
    # depender del bitrate exacto.
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


def _similar(
    left: dict,
    right: dict,
) -> bool:

    if fuzz.token_sort_ratio(
        left["artist_key"],
        right["artist_key"],
    ) < MIN_ARTIST_SIMILARITY:
        return False

    if fuzz.token_set_ratio(
        left["title_key"],
        right["title_key"],
    ) < MIN_TITLE_SIMILARITY:
        return False

    return True


def find_duplicates() -> list:
    entries = []

    for path in _iter_audio_files():
        artist, title = _identify(path)

        artist_key = normalize_text(artist)
        title_key = normalize_text(title)

        if not artist_key or not title_key:
            continue

        entries.append(
            {
                "path": path,
                "artist": artist,
                "title": title,
                "artist_key": artist_key,
                "title_key": title_key,
                "block": artist_key[:3],
            }
        )

    # Agrupamos por bloques del artista para no
    # comparar todo contra todo (las bibliotecas
    # grandes harían O(n²) inviable).
    blocks = {}

    for entry in entries:
        blocks.setdefault(
            entry["block"],
            [],
        ).append(entry)

    groups = []

    for block_entries in blocks.values():
        local_groups = []

        for entry in block_entries:
            target = None

            for candidate in local_groups:
                if any(
                    _similar(entry, member)
                    for member in candidate
                ):
                    target = candidate

                    break

            if target is None:
                target = []
                local_groups.append(target)

            target.append(entry)

        for local_group in local_groups:
            if len(local_group) < 2:
                continue

            members = sorted(
                local_group,
                key=lambda item: _quality_rank(item["path"]),
                reverse=True,
            )

            groups.append(
                {
                    "artist": members[0]["artist"],
                    "title": members[0]["title"],
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


def _iter_playlist_files():
    # Navidrome importa los .m3u de CUALQUIER
    # carpeta de la biblioteca, no solo de
    # PLAYLISTS; escaneamos igual que él.
    for path in sorted(
        LIBRARY_ROOT.rglob("*")
    ):
        if not path.is_file():
            continue

        if path.suffix.casefold() not in M3U_EXTENSIONS:
            continue

        if path.name.endswith(".tmp"):
            continue

        yield path


def _find_playlist_file(
    name: str,
) -> Path | None:

    requested = name.casefold().strip()

    for path in _iter_playlist_files():
        if (
            path.stem.casefold().strip()
            == requested
        ):
            return path

    return None


def playlist_orphans_report() -> list:
    reports = []

    for playlist_file in _iter_playlist_files():
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


def delete_playlist(
    name: str,
) -> dict:
    playlist_file = _find_playlist_file(name)

    if playlist_file is None:
        return {
            "status": "not_found",
        }

    try:
        playlist_file.unlink()

    except OSError as error:
        return {
            "status": "error",
            "error": str(error),
        }

    logger.warning(
        f"[PLAYLIST DELETED] file={str(playlist_file)!r}"
    )

    return {
        "status": "deleted",
        "name": playlist_file.stem,
    }


def prune_playlist(
    name: str,
    delete_if_empty: bool = False,
) -> dict:
    playlist_file = _find_playlist_file(name)

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
