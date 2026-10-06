"""Unit tests for download cancel / size / allowlist (no network)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model_download as md


class FakeResp:
    def __init__(self, data: bytes, headers=None):
        self._data = data
        self.headers = headers or {"Content-Length": str(len(data)), "Content-Type": "application/octet-stream"}
        self._pos = 0

    def read(self, n=-1):
        if self._pos >= len(self._data):
            return b""
        if n is None or n < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadHelpersTest(unittest.TestCase):
    def test_allowlist(self):
        self.assertTrue(md.is_allowed_url("https://github.com/ACEsuit/mace-foundations/releases/download/x/a.model"))
        self.assertTrue(md.is_allowed_url("https://raw.githubusercontent.com/ACEsuit/mace-off/main/a.model"))
        self.assertTrue(md.is_allowed_url("https://huggingface.co/org/repo/resolve/main/a.model"))
        self.assertFalse(md.is_allowed_url("http://github.com/x"))
        self.assertFalse(md.is_allowed_url("https://evil.example/a.model"))

    def test_safe_filename(self):
        self.assertEqual(md.safe_filename(None, "https://x/y/z.model"), "z.model")
        self.assertEqual(md.safe_filename("mine.model", "https://x/y/z.model"), "mine.model")
        with self.assertRaises(md.DownloadError):
            md.safe_filename("../etc/passwd", "https://x/y/z.model")

    def test_validate_size(self):
        md.validate_size(10_000, 10_000)
        md.validate_size(10_000, None)
        with self.assertRaises(md.DownloadError):
            md.validate_size(100, 10_000)
        with self.assertRaises(md.DownloadError):
            md.validate_size(500, None)  # empty-ish

    def test_part_rename_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.model"
            data = b"x" * 5000
            n = md.write_part_then_rename(dest, data)
            self.assertEqual(n, 5000)
            self.assertTrue(dest.is_file())
            self.assertFalse(Path(str(dest) + ".part").exists())

            dest2 = Path(tmp) / "b.model"
            with self.assertRaises(md.DownloadCancelled):
                md.write_part_then_rename(dest2, data, cancel_after=100)
            self.assertFalse(dest2.exists())
            self.assertFalse(Path(str(dest2) + ".part").exists())

    def test_job_success_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = b"MODEL" * 2000

            def fetch(_url):
                return FakeResp(payload)

            mgr = md.DownloadManager(fetch=fetch)
            job = mgr.start(
                url="https://github.com/ACEsuit/mace-foundations/releases/download/x/a.model",
                dest_dir=tmp,
                filename="a.model",
                expected_size=len(payload),
            )
            for _ in range(200):
                snap = job.snapshot()
                if snap["status"] in ("done", "error", "cancelled"):
                    break
                import time

                time.sleep(0.01)
            self.assertEqual(job.snapshot()["status"], "done")
            self.assertTrue(Path(tmp, "a.model").is_file())

            # Cancel mid-flight with a slow reader
            class SlowResp(FakeResp):
                def read(self, n=-1):
                    import time

                    time.sleep(0.05)
                    return super().read(n)

            def slow_fetch(_url):
                return SlowResp(b"Z" * 200_000)

            mgr2 = md.DownloadManager(fetch=slow_fetch)
            job2 = mgr2.start(
                url="https://raw.githubusercontent.com/ACEsuit/mace-off/main/x.model",
                dest_dir=tmp,
                filename="slow.model",
            )
            import time

            time.sleep(0.02)
            self.assertTrue(mgr2.cancel(job2.id))
            for _ in range(200):
                if job2.snapshot()["status"] in ("cancelled", "error", "done"):
                    break
                time.sleep(0.02)
            self.assertEqual(job2.snapshot()["status"], "cancelled")
            self.assertFalse(Path(tmp, "slow.model").exists())
            self.assertFalse(Path(tmp, "slow.model.part").exists())


if __name__ == "__main__":
    unittest.main()
