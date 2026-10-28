"""Self-update from GitHub Releases.

How it works
------------
Every release publishes two assets (see ``.github/workflows/release.yml``):

* ``DataMapperX.exe``  - the application
* ``latest.json``      - ``{"version", "min_supported", "sha256", "size", "notes", ...}``

The app reads ``releases/latest/download/latest.json``. That is a plain web download, not an
API call, so it is not subject to the 60-requests-per-hour API limit that a whole site behind
one corporate proxy would otherwise exhaust.

Installing replaces the running exe. Windows allows *renaming* a running executable but not
overwriting it, so the sequence is: download next to the exe -> verify SHA-256 -> rename the
running exe to ``.old`` -> move the new file into place -> start it -> exit. ``.old`` is deleted
on the next launch.

Nothing in this module imports tkinter, so it can be tested without a display.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ._version import __version__
from .config import APP_TITLE, GITHUB_REPO
from .paths import is_frozen

logger = logging.getLogger(__name__)

RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
MANIFEST_URL = f"{RELEASES_URL}/latest/download/latest.json"
ASSET_NAME = "DataMapperX.exe"

# Downloads may only come from GitHub (release assets are served from githubusercontent.com).
_ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")
_USER_AGENT = f"{APP_TITLE}/{__version__} (+https://github.com/{GITHUB_REPO})"
_MAX_MANIFEST_BYTES = 256 * 1024
_CHUNK = 256 * 1024

ProgressCallback = Callable[[int, int], None]  # (bytes done, bytes total or 0)


class UpdateError(Exception):
    """The check, download or install failed. The message is safe to show to the user."""


class UpdateCancelled(UpdateError):
    pass


# -----------------------------------------------------------------------------
# Versions
# -----------------------------------------------------------------------------
def parse_version(text: str) -> tuple[int, int, int]:
    """'v1.2.3' -> (1, 2, 3). Missing parts count as 0; pre-release suffixes are ignored."""
    match = re.match(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text), re.IGNORECASE)
    if not match:
        raise ValueError(f"Not a version number: {text!r}")
    major, minor, patch = (int(part or 0) for part in match.groups())
    return major, minor, patch


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# -----------------------------------------------------------------------------
# Manifest
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    min_supported: str
    notes: str
    published_at: str
    asset_url: str
    sha256: str
    size: int

    def is_mandatory_for(self, current: str) -> bool:
        """True when the running version is older than the lowest version still supported."""
        return bool(self.min_supported) and parse_version(current) < parse_version(self.min_supported)


def parse_manifest(data: object) -> UpdateInfo:
    if not isinstance(data, dict):
        raise UpdateError("The update manifest is not a JSON object.")
    try:
        version = str(data["version"]).lstrip("vV")
        parse_version(version)
        asset = str(data.get("asset") or ASSET_NAME)
        if not re.fullmatch(r"[\w.\-]+", asset):
            raise ValueError(f"unsafe asset name {asset!r}")
        sha256 = str(data["sha256"]).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("sha256 must be 64 hex characters")
        min_supported = str(data.get("min_supported") or "")
        if min_supported:
            parse_version(min_supported)
        size = int(data.get("size") or 0)
    except (KeyError, ValueError, TypeError) as exc:
        raise UpdateError(f"The update manifest is invalid: {exc}") from exc

    # The URL is built here, never taken from the manifest, so the manifest cannot redirect the download.
    return UpdateInfo(
        version=version,
        min_supported=min_supported,
        notes=str(data.get("notes") or "").strip(),
        published_at=str(data.get("published_at") or ""),
        asset_url=f"{RELEASES_URL}/download/v{version}/{asset}",
        sha256=sha256,
        size=size,
    )


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES)
    if parsed.scheme != "https" or not allowed:
        raise UpdateError(f"Refusing to use a non-GitHub address: {parsed.scheme}://{host}")


def _open(url: str, timeout: float):
    import urllib.request  # here, not at the top: it pulls in ssl and http, which the window does not need to open

    _check_host(url)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Cache-Control": "no-cache"})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"GitHub answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not reach GitHub: {getattr(exc, 'reason', exc)}") from exc
    try:
        _check_host(response.geturl())  # after redirects
    except UpdateError:
        response.close()
        raise
    return response


def fetch_update_info(timeout: float = 8.0) -> UpdateInfo:
    with _open(MANIFEST_URL, timeout) as response:
        raw = response.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise UpdateError("The update manifest is unexpectedly large.")
    try:
        return parse_manifest(json.loads(raw.decode("utf-8")))
    except ValueError as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"The update manifest is not valid JSON: {exc}") from exc


def check_for_update(current: str = __version__, timeout: float = 8.0) -> UpdateInfo | None:
    """Return the newer release, or ``None`` when already up to date. Raises ``UpdateError`` otherwise."""
    info = fetch_update_info(timeout)
    if is_newer(info.version, current):
        logger.info("Update available: %s -> %s", current, info.version)
        return info
    logger.info("Up to date (%s)", current)
    return None


# -----------------------------------------------------------------------------
# Download
# -----------------------------------------------------------------------------
def download_update(
    info: UpdateInfo,
    dest: Path,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 30.0,
) -> None:
    """Download ``info.asset_url`` to ``dest`` and verify size, PE header and SHA-256."""
    digest = hashlib.sha256()
    written = 0
    try:
        with _open(info.asset_url, timeout) as response, open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length") or info.size or 0)
            first = True
            while chunk := response.read(_CHUNK):
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateCancelled("Download cancelled.")
                if first and not chunk.startswith(b"MZ"):
                    raise UpdateError("The downloaded file is not a Windows program.")
                first = False
                out.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
        if info.size and written != info.size:
            raise UpdateError(f"Download is incomplete ({written} of {info.size} bytes).")
        if digest.hexdigest() != info.sha256:
            raise UpdateError("The downloaded file failed its SHA-256 check and was discarded.")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------
def current_exe() -> Path:
    return Path(sys.executable).resolve()


def staging_path(exe: Path | None = None) -> Path:
    """Where the new exe is downloaded: same folder, so the final rename is atomic on the same volume."""
    exe = exe or current_exe()
    return exe.with_name(exe.name + ".new")


def _folder_is_writable(folder: Path) -> bool:
    probe = folder / f".dmx_write_test_{os.getpid()}"
    try:
        probe.write_bytes(b"")
    except OSError:
        return False
    probe.unlink(missing_ok=True)
    return True


def can_self_update() -> bool:
    """Only a frozen Windows exe in a folder we can write to can replace itself."""
    return sys.platform == "win32" and is_frozen() and _folder_is_writable(current_exe().parent)


def relaunch_app(exe: Path) -> None:
    env = os.environ.copy()
    # Tell the PyInstaller bootloader this is a fresh, independent start and not a child of the
    # process that is about to exit (otherwise it would reuse a temp folder that is deleted on exit).
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent), close_fds=True, creationflags=flags)


def install_update(
    new_exe: Path,
    *,
    target: Path | None = None,
    relaunch: Callable[[Path], None] | None = relaunch_app,
) -> None:
    """Swap ``new_exe`` in for the running program. The caller must exit right after this returns."""
    target = target or current_exe()
    backup = target.with_name(target.name + ".old")

    if not new_exe.is_file():
        raise UpdateError("The downloaded update is missing.")

    try:
        backup.unlink(missing_ok=True)
        os.replace(target, backup)  # allowed while running
    except OSError as exc:
        raise UpdateError(f"Could not move the current program aside: {exc}") from exc

    try:
        os.replace(new_exe, target)
    except OSError as exc:
        try:
            os.replace(backup, target)  # roll back so the user is left with a working app
        except OSError:
            logger.exception("Rollback failed; previous version is at %s", backup)
        raise UpdateError(f"Could not put the new version in place: {exc}") from exc

    logger.info("Installed update at %s (previous version kept as %s until next start)", target, backup.name)
    if relaunch is not None:
        try:
            relaunch(target)
        except OSError as exc:
            raise UpdateError(
                f"The update was installed but could not be restarted automatically ({exc}). "
                "Please start DataMapperX again."
            ) from exc


def cleanup_update_leftovers(exe: Path | None = None) -> None:
    """Remove files a previous update left next to the exe. Safe to call on every start."""
    if exe is None:
        if not is_frozen():
            return  # a source checkout runs under python.exe; never touch the interpreter's folder
        exe = current_exe()
    for leftover in (exe.with_name(exe.name + ".old"), exe.with_name(exe.name + ".new")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not remove %s yet", leftover)
