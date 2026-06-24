from __future__ import annotations

import json
import subprocess
import sys
import threading
import tempfile
from pathlib import Path


class ExifToolSession:
    """Persistent ExifTool process using -stay_open for faster batch reads/writes."""

    def __init__(self, exiftool_path: Path, charset_args: list[str]) -> None:
        self._exiftool_path = exiftool_path
        self._charset_args = charset_args
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None

    def close(self) -> None:
        with self._lock:
            self._terminate_unlocked()

    def _terminate_unlocked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write("{ready}\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._terminate_unlocked()
        args = [
            str(self._exiftool_path),
            "-stay_open",
            "True",
            "-@", "-",
            *self._charset_args,
        ]
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return self._proc

    def _execute(self, command_lines: list[str], *, timeout: int = 120) -> tuple[int, str, str]:
        with self._lock:
            proc = self._ensure_process()
            assert proc.stdin is not None
            assert proc.stdout is not None
            assert proc.stderr is not None
            for line in command_lines:
                proc.stdin.write(f"{line}\n")
            proc.stdin.write("-execute\n")
            proc.stdin.flush()

            stdout_parts: list[str] = []
            while True:
                line = proc.stdout.readline()
                if not line:
                    self._terminate_unlocked()
                    raise RuntimeError("ExifTool stay-open session ended unexpectedly")
                if line.strip() == "{ready}":
                    break
                stdout_parts.append(line)
            stderr = proc.stderr.read() if proc.stderr else ""
            return proc.returncode or 0, "".join(stdout_parts), stderr

    def read_json_batch(self, paths: list[Path], read_fields: tuple[str, ...], *, timeout: int = 120) -> list[dict]:
        if not paths:
            return []
        argfile = self._write_path_argfile(paths)
        try:
            command = ["-json", "-s", "-s", "-s"]
            command.extend(f"-{field}" for field in read_fields)
            command.extend(["-@", str(argfile)])
            _rc, stdout, _stderr = self._execute(command, timeout=timeout)
            payload = json.loads(stdout or "[]")
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
            return []
        except Exception:
            self._terminate_unlocked()
            raise
        finally:
            argfile.unlink(missing_ok=True)

    def write_json_batch(self, file_path: Path, payload_json: Path, *, timeout: int = 120) -> tuple[int, str, str]:
        command = [
            "-overwrite_original",
            f"-j={payload_json}",
            str(file_path.resolve()),
        ]
        try:
            return self._execute(command, timeout=timeout)
        except Exception:
            self._terminate_unlocked()
            raise

    @staticmethod
    def _write_path_argfile(paths: list[Path]) -> Path:
        import os

        fd, name = tempfile.mkstemp(prefix="media_paths_", suffix=".txt")
        os.close(fd)
        argfile = Path(name)
        lines = "\n".join(str(path.resolve()) for path in paths)
        argfile.write_text(f"{lines}\n", encoding="utf-8")
        return argfile


def run_exiftool_subprocess(
    exiftool_path: Path,
    args: list[str],
    paths: list[Path],
    *,
    charset_args: list[str],
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    import os

    if not paths:
        return subprocess.CompletedProcess(args, 1, "", "No paths")
    fd, name = tempfile.mkstemp(prefix="media_paths_", suffix=".txt")
    os.close(fd)
    argfile = Path(name)
    try:
        lines = "\n".join(str(path.resolve()) for path in paths)
        argfile.write_text(f"{lines}\n", encoding="utf-8")
        full_args = [str(exiftool_path), *args, *charset_args, "-@", str(argfile)]
        return subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    finally:
        argfile.unlink(missing_ok=True)
