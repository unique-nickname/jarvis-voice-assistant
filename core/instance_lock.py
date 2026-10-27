"""Prevent multiple Jarvis runtimes from sharing user-scoped resources."""

from __future__ import annotations

import fcntl
import os
import stat
from pathlib import Path


class JarvisAlreadyRunningError(RuntimeError):
    """Raised when another Jarvis process owns the per-user runtime lock."""


class JarvisInstanceLock:
    """Hold an advisory lock for the lifetime of one Jarvis runtime."""

    def __init__(self, descriptor: int, path: Path) -> None:
        self._descriptor: int | None = descriptor
        self.path = path

    @classmethod
    def acquire(cls) -> JarvisInstanceLock:
        lock_directory = Path.home() / ".local" / "state" / "jarvis"
        try:
            lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory_info = lock_directory.lstat()
            if (
                not stat.S_ISDIR(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid()
            ):
                raise RuntimeError("Jarvis's runtime directory is not privately owned.")
            lock_directory.chmod(0o700)
        except OSError as exc:
            raise RuntimeError(
                "Could not prepare Jarvis's private runtime directory."
            ) from exc

        lock_path = lock_directory / "instance.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError("Could not open Jarvis's runtime lock file.") from exc

        try:
            file_info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_info.st_mode)
                or file_info.st_uid != os.geteuid()
            ):
                raise RuntimeError(
                    "Jarvis's runtime lock file is not a private regular file."
                )
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise JarvisAlreadyRunningError(
                    "Another Jarvis process is already running."
                ) from exc
        except BaseException:
            os.close(descriptor)
            raise

        return cls(descriptor, lock_path)

    def close(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> JarvisInstanceLock:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
