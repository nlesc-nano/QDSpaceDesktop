"""Foundation-model download jobs for the Predict sidecar.

Writes to ``.part`` then renames. Host allowlist only; used by unit tests
without network by injecting a fetch function.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "raw.githubusercontent.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "hf.co",
    }
)

FetchFn = Callable[[str], object]  # returns a context-manager response with .headers and .read


class DownloadCancelled(Exception):
    pass


class DownloadError(Exception):
    pass


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in ALLOWED_HOSTS:
        return True
    # Allow nested GitHub / HF CDN hosts such as *.githubusercontent.com
    return host.endswith(".githubusercontent.com") or host.endswith(".hf.co")


def safe_filename(name: Optional[str], url: str) -> str:
    candidate = (name or "").strip()
    if candidate and ("/" in candidate or chr(92) in candidate or ".." in candidate):
        raise DownloadError("Invalid download filename")
    raw = candidate or Path(urlparse(url).path).name or "model.model"
    raw = Path(raw).name
    if not raw or raw in {".", ".."}:
        raise DownloadError("Invalid download filename")
    return raw


def validate_size(actual: int, expected: Optional[int], tolerance: float = 0.05) -> None:
    """Rough size check: reject empty files and large mismatches when expected is known."""
    if actual < 1024:
        raise DownloadError("Downloaded file looks empty")
    if expected is None or expected <= 0:
        return
    lo = int(expected * (1.0 - tolerance))
    hi = int(expected * (1.0 + tolerance))
    if actual < lo or actual > hi:
        raise DownloadError(
            f"Downloaded size {actual} bytes does not match expected ~{expected} bytes"
        )


def default_fetch(url: str):
    req = Request(url, headers={"User-Agent": "QDSpaceDesktop-MACE-downloader/1.0"})
    return urlopen(req, timeout=120)


class DownloadJob:
    def __init__(
        self,
        job_id: str,
        url: str,
        dest: Path,
        expected_size: Optional[int] = None,
        sha256: Optional[str] = None,
    ):
        self.id = job_id
        self.url = url
        self.dest = dest
        self.expected_size = expected_size
        self.sha256 = (sha256 or "").strip().lower() or None
        self.status = "starting"  # starting|running|done|cancelled|error
        self.bytes_done = 0
        self.bytes_total: Optional[int] = expected_size
        self.path: Optional[str] = None
        self.error: Optional[str] = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def request_cancel(self) -> None:
        self._cancel.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "bytes_done": self.bytes_done,
                "bytes_total": self.bytes_total,
                "path": self.path,
                "error": self.error,
                "url": self.url,
            }

    def _set(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def run(self, fetch: Optional[FetchFn] = None) -> None:
        fetch = fetch or default_fetch
        part = Path(str(self.dest) + ".part")
        try:
            if not is_allowed_url(self.url):
                raise DownloadError("Download host is not allowlisted")
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            if part.exists():
                part.unlink()
            self._set(status="running")
            hasher = hashlib.sha256() if self.sha256 else None
            with fetch(self.url) as resp:
                headers = getattr(resp, "headers", {}) or {}
                content_type = ""
                try:
                    content_type = (headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                except Exception:
                    content_type = ""
                if content_type == "text/html":
                    raise DownloadError("Download returned HTML instead of a model file")
                try:
                    total = int(headers.get("Content-Length") or 0) or None
                except Exception:
                    total = None
                if total:
                    self._set(bytes_total=total)
                elif self.expected_size:
                    self._set(bytes_total=self.expected_size)

                done = 0
                with open(part, "wb") as out:
                    while True:
                        if self._cancel.is_set():
                            raise DownloadCancelled("Download cancelled")
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
                        done += len(chunk)
                        self._set(bytes_done=done)

            validate_size(done, self.expected_size or self.bytes_total)
            if hasher is not None and self.sha256:
                digest = hasher.hexdigest()
                if digest != self.sha256:
                    raise DownloadError(f"SHA-256 mismatch (got {digest})")

            if self.dest.exists():
                self.dest.unlink()
            part.replace(self.dest)
            self._set(status="done", path=str(self.dest.resolve()), bytes_done=done)
        except DownloadCancelled:
            self._cleanup(part)
            self._set(status="cancelled", error="Download cancelled")
        except Exception as e:
            self._cleanup(part)
            self._set(status="error", error=str(e))

    def _cleanup(self, part: Path) -> None:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass


class DownloadManager:
    def __init__(self, fetch: Optional[FetchFn] = None):
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        self._fetch = fetch

    def start(
        self,
        url: str,
        dest_dir: str,
        filename: Optional[str] = None,
        expected_size: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> DownloadJob:
        if not is_allowed_url(url):
            raise DownloadError("Download host is not allowlisted")
        name = safe_filename(filename, url)
        dest = Path(dest_dir).expanduser().resolve() / name
        if not dest.parent.is_dir():
            raise DownloadError(f"Destination folder does not exist: {dest.parent}")
        job_id = uuid.uuid4().hex
        job = DownloadJob(job_id, url, dest, expected_size=expected_size, sha256=sha256)
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=job.run, kwargs={"fetch": self._fetch}, daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Optional[DownloadJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job.request_cancel()
        return True


# Pure helpers for unit tests (no threads / network).
def write_part_then_rename(dest: Path, data: bytes, cancel_after: Optional[int] = None) -> int:
    """Simulate the .part → rename write path. If cancel_after is set, raises DownloadCancelled."""
    part = Path(str(dest) + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(part, "wb") as out:
            for i in range(0, len(data), 64):
                if cancel_after is not None and written >= cancel_after:
                    raise DownloadCancelled("Download cancelled")
                chunk = data[i : i + 64]
                out.write(chunk)
                written += len(chunk)
        if dest.exists():
            dest.unlink()
        part.replace(dest)
        return written
    except DownloadCancelled:
        if part.exists():
            part.unlink()
        raise
