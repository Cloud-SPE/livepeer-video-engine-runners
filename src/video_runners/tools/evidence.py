"""Versioned, private run evidence and cooperative host validation leases."""

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

LOCK_ROOT = Path("/tmp")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(value, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink()
            raise
    os.replace(temporary, path)


def source_identity(root: Path) -> dict:
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
        ).strip()

    try:
        revision = git("rev-parse", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=normal"))
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None
    return {
        "revision": revision,
        "dirty": dirty,
        "worktree_id": hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:10],
    }


class RunReceipt:
    def __init__(self, root: Path, output: Path, kind: str):
        source = source_identity(root)
        self.id = f"vr-{source['worktree_id']}-{uuid.uuid4().hex[:12]}"
        output.mkdir(parents=True, exist_ok=True)
        self.directory = output.resolve() / self.id
        self.directory.mkdir(mode=0o700)
        self.data = {
            "schema_version": 1,
            "run_id": self.id,
            "kind": kind,
            "parent_run_id": None,
            "source": source,
            "started_at": now(),
            "status": "running",
            "outcome": "unknown",
            "inputs": {},
            "results": [],
        }
        parent = os.environ.get("VIDEO_VALIDATION_PARENT_RUN", "")
        if re.fullmatch(r"vr-[0-9a-f]{10}-[0-9a-f]{12}", parent):
            self.data["parent_run_id"] = parent
        self.save()

    def save(self):
        atomic_json(self.directory / "receipt.json", self.data)

    def result(self, value: dict):
        self.data["results"].append(value)
        self.save()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        self.data.update(
            finished_at=now(), status="passed" if kind is None else "failed"
        )
        if kind is None and self.data["outcome"] == "unknown":
            self.data["outcome"] = "verified"
        elif kind is not None:
            self.data["outcome"] = "unknown"
            self.data["error_type"] = kind.__name__
        self.save()
        print(
            f"Run receipt: {self.directory / 'receipt.json'}",
            file=sys.stderr,
            flush=True,
        )


class HostLease:
    """Same-user, same-host coordination; not authority over unrelated GPU apps."""

    def __init__(self, name="gpu-validation", inherited=True, wait=False):
        directory = LOCK_ROOT / f"livepeer-video-{os.getuid()}"
        directory.mkdir(mode=0o700, exist_ok=True)
        if (
            directory.is_symlink()
            or directory.stat().st_uid != os.getuid()
            or directory.stat().st_mode & 0o077
        ):
            raise RuntimeError("unsafe validation lock directory")
        path = directory / (name + ".lock")
        inherited_fd = (
            os.environ.get("VIDEO_VALIDATION_LEASE_FD")
            if inherited and name == "gpu-validation"
            else None
        )
        if inherited_fd is not None:
            original = int(inherited_fd)
            expected, actual = path.stat(), os.fstat(original)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise RuntimeError("inherited validation lease differs")
            self.fd = os.dup(original)
        else:
            self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError:
            os.close(self.fd)
            raise RuntimeError(f"another process holds the {name} lease") from None

    def child_env(self, run_id):
        return {
            **os.environ,
            "VIDEO_VALIDATION_LEASE_FD": str(self.fd),
            "VIDEO_VALIDATION_PARENT_RUN": run_id,
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Closing the inherited descriptor must not unlock the parent's open
        # file description. The final close releases the cooperative lease.
        os.close(self.fd)


def model_inputs(root: Path, engine: str, model: str, container="") -> dict:
    name = model.removeprefix(engine + "-")
    manifest = json.loads((root / "configs/model-assets.json").read_text())
    images = json.loads((root / "configs/engine-images.json").read_text())
    plan = manifest["models"][engine][name]
    result = {
        "engine": engine,
        "model": model,
        "assets": [
            {key: asset[key] for key in ("repo", "revision")}
            for asset in [plan, *plan.get("extra_files", [])]
        ],
        "expected_images": images if engine == "lightx2v" else {engine: images[engine]},
    }
    result["observed_engine"] = None
    if container:
        actual = json.loads(
            subprocess.check_output(
                ["docker", "inspect", "--type", "container", container], text=True
            )
        )[0]
        result["observed_engine"] = {
            "container_id": actual["Id"],
            "image_id": actual["Image"],
            "image_reference": actual["Config"]["Image"],
        }
    return result
