"""Durable controller state and exclusive state/GPU leases."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import tempfile
from pathlib import Path
import aiohttp
from video_runners.contracts import EngineError
from video_runners.controller.policy import Policy
from video_runners.controller.docker import Docker


class ControllerState:
    def __init__(
        self,
        policy: Policy,
        docker: Docker,
        http: aiohttp.ClientSession,
        directory: Path,
        lease_directory: Path | None = None,
    ) -> None:
        self.policy, self.docker, self.http = policy, docker, http
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lease = (directory / "controller.lock").open("a")
        self.gpu_lease = None
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            raise ValueError("another controller owns this state directory") from None
        self.path = directory / "state.json"
        try:
            if policy.gpu:
                if lease_directory is None:
                    raise ValueError("a shared GPU lease directory is required")
                lease_directory.mkdir(parents=True, exist_ok=True)
                self.gpu_lease = (lease_directory / (policy.gpu + ".lock")).open("a")
                try:
                    fcntl.flock(self.gpu_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError(
                        "another controller owns the assigned GPU"
                    ) from None
            self.state = (
                json.loads(self.path.read_text())
                if self.path.exists()
                else {
                    "version": 1,
                    "namespace": policy.namespace,
                    "active": None,
                    "last_good": None,
                    "enabled": False,
                    "containers": {},
                    "operations": {},
                }
            )
            if (
                self.state["version"] != 1
                or self.state["namespace"] != policy.namespace
            ):
                raise ValueError(
                    "controller state belongs to a different namespace or version"
                )
        except Exception:
            if self.gpu_lease is not None:
                self.gpu_lease.close()
            self.lease.close()
            raise
        self.phase, self.error = "recovering", ""
        self.task: asyncio.Task | None = None

    def save(self) -> None:
        try:
            self._save()
        except OSError as exc:
            self.phase, self.error = "error", "controller state could not be persisted"
            raise EngineError(self.error) from exc

    def _save(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.directory, delete=False
        ) as file:
            json.dump(self.state, file)
            file.flush()
            os.fsync(file.fileno())
            name = file.name
        os.replace(name, self.path)
        fd = os.open(self.directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
