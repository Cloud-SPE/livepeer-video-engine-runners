"""Only verified run resources can be deleted; foreign state stays untouched."""

from copy import deepcopy
import json

import pytest

from video_runners.tools.cpu_harness import LABEL, capture, cleanup_manifest, resource
from video_runners.tools.evidence import atomic_json
from video_runners.controller.policy import Policy

RUN = "vr-" + "a" * 10 + "-" + "b" * 12


class Daemon:
    def __init__(self, objects):
        self.objects = objects
        self.deleted = []

    def inspect(self, kind, identifier):
        return deepcopy(self.objects.get((kind, identifier)))

    def ids(self, kind, label):
        key, value = label.split("=", 1)
        return [
            identifier
            for (category, identifier), obj in self.objects.items()
            if category == kind
            and (obj.get("Labels") or obj.get("Config", {}).get("Labels", {})).get(key)
            == value
        ]

    def call(self, *args):
        if args[:1] == ("info",):
            return "daemon-one"
        if args[:1] == ("exec",):
            return json.dumps(self.state)
        if args[1] == "rm":
            self.deleted.append(args)
            del self.objects[(args[0], args[2])]
            return ""
        raise AssertionError(args)


def manifest(tmp_path, daemon, records):
    path = tmp_path / "resources.json"
    atomic_json(
        path,
        {
            "schema_version": 1,
            "run_id": RUN,
            "daemon_id": "daemon-one",
            "image_tags": {},
            "service_images": {},
            "resources": records,
        },
    )
    return path


def test_cleanup_is_idempotent_and_leaves_foreign_volumes(tmp_path):
    owned = {"Name": RUN + "-state", "Driver": "local", "Labels": {LABEL: RUN}}
    wallet = {"Name": "operator-wallet-data", "Driver": "local", "Labels": {}}
    daemon = Daemon(
        {("volume", owned["Name"]): owned, ("volume", wallet["Name"]): wallet}
    )
    path = manifest(tmp_path, daemon, [resource("volume", owned)])
    atomic_json(
        tmp_path / "receipt.json",
        {
            "schema_version": 1,
            "run_id": RUN,
            "status": "failed",
            "outcome": "unknown",
            "cleanup": "review_required",
        },
    )
    cleanup_manifest(path, daemon)
    cleanup_manifest(path, daemon)
    assert daemon.deleted == [("volume", "rm", owned["Name"])]
    assert daemon.inspect("volume", "operator-wallet-data") == wallet
    assert json.loads(path.read_text())["cleanup"] == "complete"
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert (
        receipt["cleanup"] == "complete"
        and receipt["status"] == "failed"
        and receipt["outcome"] == "unknown"
    )


@pytest.mark.parametrize("failure", ["labels", "options", "foreign-name", "daemon"])
def test_cleanup_refuses_drift_before_any_deletion(tmp_path, failure):
    owned = {"Name": RUN + "-state", "Driver": "local", "Labels": {LABEL: RUN}}
    if failure == "foreign-name":
        owned["Name"] = "operator-wallet-data"
    daemon = Daemon({("volume", owned["Name"]): deepcopy(owned)})
    path = manifest(tmp_path, daemon, [resource("volume", owned)])
    if failure == "labels":
        daemon.objects[("volume", owned["Name"])]["Labels"] = {LABEL: "other"}
    elif failure == "options":
        daemon.objects[("volume", owned["Name"])]["Options"] = {"device": "/unrelated"}
    elif failure == "daemon":
        data = json.loads(path.read_text())
        data["daemon_id"] = "different"
        atomic_json(path, data)
    with pytest.raises(RuntimeError):
        cleanup_manifest(path, daemon)
    assert daemon.deleted == []


def test_cleanup_does_not_adopt_unrecorded_engines_by_label(tmp_path):
    engine = {
        "Config": {
            "Labels": {
                "io.livepeer.video.owner": RUN,
                "com.docker.compose.project": RUN,
                "com.docker.compose.service": "engine-image",
            }
        }
    }
    daemon = Daemon({("container", "c" * 64): engine})
    path = manifest(tmp_path, daemon, [])
    with pytest.raises(RuntimeError, match="durable ownership"):
        cleanup_manifest(path, daemon)
    assert daemon.deleted == []


def test_capture_does_not_replace_recorded_image_after_retag(tmp_path):
    tag = f"livepeer-video-test-{RUN}:runner"
    original = {"Id": "sha256:" + "a" * 64, "Config": {"Labels": {LABEL: RUN}}}
    daemon = Daemon({("image", tag): original})
    path = manifest(tmp_path, daemon, [])
    data = json.loads(path.read_text())
    data["image_tags"] = {"runner": tag}
    atomic_json(path, data)
    capture(path, daemon)
    daemon.objects[("image", tag)]["Id"] = "sha256:" + "b" * 64
    with pytest.raises(RuntimeError, match="retagged"):
        cleanup_manifest(path, daemon)
    assert daemon.deleted == []


def test_durable_engine_ownership_takes_priority_over_inherited_compose_labels(
    tmp_path,
):
    engine_image = "sha256:" + "e" * 64
    controller_image = "sha256:" + "f" * 64
    raw = {
        "namespace": RUN,
        "network": RUN + "-engine",
        "gpu": None,
        "allow_local_images": True,
        "models": {"first": {"image": engine_image, "command": ["engine"]}},
    }
    payload = Policy(deepcopy(raw)).payloads["first"]
    engine = {
        "Id": "a" * 64,
        "Name": "/" + RUN + "-random",
        "Image": engine_image,
        "State": {"Running": True},
        "Mounts": [],
        "Config": {
            k: v
            for k, v in payload.items()
            if k not in {"HostConfig", "NetworkingConfig"}
        },
        "HostConfig": payload["HostConfig"],
        "NetworkSettings": {"Networks": payload["NetworkingConfig"]["EndpointsConfig"]},
    }
    engine["Config"]["Labels"].update(
        {
            "com.docker.compose.project": RUN,
            "com.docker.compose.service": "engine-image",
        }
    )
    controller = {
        "Id": "b" * 64,
        "Name": f"/{RUN}-controller-1",
        "Image": controller_image,
        "State": {"Running": True},
        "Mounts": [],
        "Config": {
            "Labels": {
                LABEL: RUN,
                "com.docker.compose.project": RUN,
                "com.docker.compose.service": "controller",
            }
        },
        "HostConfig": {},
        "NetworkSettings": {"Networks": {}},
    }
    objects = {
        ("container", engine["Id"]): engine,
        ("container", controller["Id"]): controller,
        ("image", engine_image): {"Id": engine_image},
        ("image", controller_image): {"Id": controller_image},
    }
    daemon = Daemon(objects)
    daemon.state = {"namespace": RUN, "containers": {engine["Id"]: "first"}}
    path = manifest(tmp_path, daemon, [])
    data = json.loads(path.read_text())
    data.update(
        service_images={"controller": controller_image, "engine-image": engine_image},
        engine_policy=raw,
    )
    atomic_json(path, data)
    result = capture(path, daemon)
    assert {r["role"] for r in result["resources"]} == {"controller", "managed-engine"}
    assert capture(path, daemon) == result


def test_cleanup_rechecks_configuration_immediately_before_removal(tmp_path):
    owned = {"Name": RUN + "-state", "Driver": "local", "Labels": {LABEL: RUN}}

    class ChangedAfterPreflight(Daemon):
        reads = 0

        def inspect(self, kind, identifier):
            actual = super().inspect(kind, identifier)
            self.reads += 1
            if self.reads > 1:
                actual["Options"] = {"device": "/unrelated"}
            return actual

    daemon = ChangedAfterPreflight({("volume", owned["Name"]): owned})
    path = manifest(tmp_path, daemon, [resource("volume", owned)])
    with pytest.raises(RuntimeError, match="configuration drifted"):
        cleanup_manifest(path, daemon)
    assert daemon.deleted == []
