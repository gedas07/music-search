from pathlib import Path
import logging
import os
import re
import shutil
import threading
import time

import mutagen

from .manual_playlist_service import (
    AUDIO_EXTENSIONS,
    DOWNLOADS_ROOT,
    LIBRARY_ROOT,
)
from ..slskd import SlskdClient


logger = logging.getLogger(__name__)

ORGANIZER_INTERVAL = int(
    os.getenv(
        "ORGANIZER_INTERVAL_SECONDS",
        "90",
    )
)

# Barrido lento de seguridad cuando no
# ha llegado ningún aviso de descargas
# nuevas completadas.
ORGANIZER_IDLE_INTERVAL = 900
FIRST_RUN_DELAY = 30

_wake = threading.Event()

# Un fichero recién tocado no se toca: damos margen
# por si slskd aún está escribiendo y la API no
# lo refleja todavía.
STABILITY_SECONDS = 180

MANAGED_TOP_DIRS = {
    "playlists_pending",
    "incomplete",
}

PLAYLIST_QUALITY_DIRS = {
    "lossless",
    "normal",
}

NOT_BUSY_MARKERS = (
    "completed",
    "succeeded",
    "aborted",
    "failed",
    "rejected",
    "errored",
    "cancel",
)


def sanitize_part(
    text: str,
) -> str:

    invalid_chars = '<>:"/\\|?*'

    sanitized = "".join(
        "_" if char in invalid_chars else char
        for char in text
    )

    sanitized = sanitized.strip().rstrip(".")

    return sanitized or "Unknown"


def read_tags(
    path: Path,
) -> dict:
    tags = {
        "artist": None,
        "album": None,
        "year": None,
        "track": None,
        "title": None,
    }

    try:
        audio = mutagen.File(
            str(path),
            easy=True,
        )

        if audio is None or audio.info is None:
            return tags

        def first(
            key,
        ):
            value = audio.get(key)

            if not value:
                return None

            text = str(value[0]).strip()

            return text or None

        tags["artist"] = first("artist")
        tags["album"] = first("album")
        tags["title"] = first("title")

        date = first("date") or first("year")

        if date:
            match = re.search(
                r"\d{4}",
                date,
            )

            if match:
                tags["year"] = match.group(0)

        track = first("tracknumber")

        if track:
            match = re.match(
                r"(\d{1,3})",
                track,
            )

            if match:
                tags["track"] = int(match.group(1))

        return tags

    except Exception:
        return tags


def _destination_filename(
    path: Path,
    tags: dict,
    artist: str,
    title: str,
) -> str:
    extension = path.suffix.casefold()

    if tags["track"] and title:
        return (
            f"{tags['track']:02d}"
            f" - {sanitize_part(title)}"
            f"{extension}"
        )

    return (
        f"{sanitize_part(artist)}"
        f" - {sanitize_part(title)}"
        f"{extension}"
    )


def organize_file(
    path: Path,
    fallback_artist: str | None = None,
    fallback_track: str | None = None,
) -> Path:
    path = Path(path)

    tags = read_tags(path)

    artist = (
        tags["artist"]
        or fallback_artist
        or path.parent.name
        or "Unknown"
    )

    title = (
        tags["title"]
        or fallback_track
        or re.sub(
            r"^\s*\d{1,3}[\s.\-_]+",
            "",
            path.stem,
        )
    )

    album = tags["album"]
    year = tags["year"]

    if album:
        album_dir = (
            f"{album} ({year})"
            if year
            else album
        )

        destination_dir = (
            LIBRARY_ROOT
            / sanitize_part(artist)
            / sanitize_part(album_dir)
        )

    else:
        destination_dir = (
            LIBRARY_ROOT
            / sanitize_part(artist)
        )

    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        destination_dir
        / _destination_filename(
            path,
            tags,
            artist,
            title,
        )
    )

    if destination.exists():
        if destination.stat().st_size == path.stat().st_size:
            path.unlink()

            logger.warning(
                f"[ORGANIZER DUPLICATE REMOVED] "
                f"source={str(path)!r} | "
                f"kept={str(destination)!r}"
            )

        else:
            destination = (
                destination_dir
                / (
                    destination.stem
                    + " (2)"
                    + destination.suffix
                )
            )

            shutil.move(
                str(path),
                str(destination),
            )

            logger.warning(
                f"[ORGANIZER MOVED VARIANT] "
                f"destination={str(destination)!r}"
            )

    else:
        shutil.move(
            str(path),
            str(destination),
        )

        logger.warning(
            f"[ORGANIZER MOVED] "
            f"source={str(path)!r} | "
            f"destination={str(destination)!r}"
        )

    _cleanup_source_dirs(path.parent)

    return destination


def _cleanup_source_dirs(
    start_dir: Path,
) -> None:
    current = start_dir

    while (
        current != DOWNLOADS_ROOT
        and DOWNLOADS_ROOT in current.parents
    ):
        try:
            current.rmdir()

        except OSError:
            break

        current = current.parent


def _is_managed_zone(
    path: Path,
) -> bool:
    try:
        relative = path.relative_to(
            DOWNLOADS_ROOT
        )

    except ValueError:
        # Fuera de /downloads: el organizador
        # no toca nada.
        return True

    parts = relative.parts

    if parts[0].casefold() in MANAGED_TOP_DIRS:
        return True

    if (
        len(parts) >= 2
        and parts[0].casefold() in PLAYLIST_QUALITY_DIRS
        and parts[1].casefold() == "playlists"
    ):
        return True

    return False


def get_busy_filenames():
    try:
        client = SlskdClient()
        client.login()

        downloads = client.get_downloads()

    except Exception as error:
        logger.warning(
            f"[ORGANIZER SLSKD ERROR] "
            f"sin información de transferencias; "
            f"sweep omitido | error={error!r}"
        )

        return None

    busy = set()

    for remote_user in downloads:
        for directory in remote_user.get(
            "directories",
            [],
        ):
            for remote_file in directory.get(
                "files",
                [],
            ):
                state = remote_file.get(
                    "state",
                    "",
                ).casefold()

                if any(
                    marker in state
                    for marker in NOT_BUSY_MARKERS
                ):
                    continue

                filename = remote_file.get(
                    "filename",
                    "",
                )

                normalized = filename.replace(
                    "\\",
                    "/",
                )

                busy.add(
                    Path(normalized).name.casefold()
                )

    return busy


def sweep_downloads() -> dict | None:
    busy = get_busy_filenames()

    if busy is None:
        return None

    now = time.time()
    moved = 0
    skipped_busy = 0

    for path in list(
        DOWNLOADS_ROOT.rglob("*")
    ):
        if not path.is_file():
            continue

        if path.suffix.casefold() not in AUDIO_EXTENSIONS:
            continue

        if _is_managed_zone(path):
            continue

        if path.name.casefold() in busy:
            skipped_busy += 1

            continue

        try:
            age = now - path.stat().st_mtime

        except OSError:
            continue

        if age < STABILITY_SECONDS:
            skipped_busy += 1

            continue

        try:
            organize_file(path)

            moved += 1

        except Exception:
            logger.exception(
                f"[ORGANIZER ERROR] path={str(path)!r}"
            )

    result = {
        "moved": moved,
        "skipped_busy": skipped_busy,
    }

    if moved or skipped_busy:
        logger.warning(
            f"[ORGANIZER SWEEP] {result}"
        )

    return result


def request_sweep():
    # Aviso barato (evento): el monitor lo usa
    # cuando detecta descargas recién completadas.
    _wake.set()


def _organizer_loop():
    time.sleep(FIRST_RUN_DELAY)

    while True:
        woke = _wake.wait(
            timeout=ORGANIZER_INTERVAL
        )

        _wake.clear()

        try:
            sweep_downloads()

        except Exception:
            logger.exception(
                "[ORGANIZER LOOP ERROR] "
                "el organizador continúa"
            )

        if woke:
            continue

        # Nadie avisó en el intervalo corto:
        # descanso largo, pero despertable.
        woke_long = _wake.wait(
            timeout=ORGANIZER_IDLE_INTERVAL
        )

        _wake.clear()

        if woke_long:
            try:
                sweep_downloads()

            except Exception:
                logger.exception(
                    "[ORGANIZER LOOP ERROR] "
                    "el organizador continúa"
                )


def start_organizer():
    thread = threading.Thread(
        target=_organizer_loop,
        daemon=True,
    )

    logger.warning("[ORGANIZER] Iniciado")

    thread.start()
