"""Exercise lifecycle policy against a recording daemon, never the host socket."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from video_runners.controller.service import Controller
from video_runners.controller.policy import MODEL, OWNER, Policy
from video_runners.controller.http import create_app
from video_runners.lifecycle.managed import ManagedSupervisor

TOKEN = "test-controller-secret-" + "a" * 32
HEADERS = {"Authorization": "Bearer " + TOKEN}


def catalog():
    return {
        "namespace": "test-controller",
        "network": "test-engines",
        "allow_local_images": True,
        "models": {
            m: {"image": "test-engine:local", "command": ["engine", m], "timeout": 1}
            for m in ("first", "second", "broken")
        },
    }


class RecordingDocker:
    def __init__(self):
        self.containers = {}
        self.calls = []
        self.serial = 0

    async def call(self, method, path, *, body=None, params=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == "/containers/json":
            owner = json.loads(params["filters"])["label"][0].split("=", 1)[1]
            return [
                {"Id": i}
                for i, c in self.containers.items()
                if c["Config"].get("Labels", {}).get(OWNER) == owner
            ]
        if path == "/containers/create":
            self.serial += 1
            identifier = f"{self.serial:064x}"
            self.containers[identifier] = {
                "Config": {
                    k: copy.deepcopy(v)
                    for k, v in body.items()
                    if k not in {"HostConfig", "NetworkingConfig"}
                },
                "HostConfig": copy.deepcopy(body["HostConfig"]),
                "State": {"Running": False},
                "NetworkSettings": {
                    "Networks": copy.deepcopy(
                        body["NetworkingConfig"]["EndpointsConfig"]
                    )
                },
            }
            return {"Id": identifier}
        identifier = path.split("/")[2]
        container = self.containers.get(identifier)
        if method == "GET":
            return copy.deepcopy(container)
        if container is None:
            return None
        if path.endswith("/start"):
            container["State"]["Running"] = (
                container["Config"]["Labels"][MODEL] != "broken"
            )
        elif path.endswith("/stop"):
            container["State"]["Running"] = False
        elif method == "DELETE":
            del self.containers[identifier]
        return {}


@asynccontextmanager
async def setup(directory, lose_response=False):
    daemon = RecordingDocker()
    health = web.Application()

    async def healthy(_):
        return web.Response()

    health.router.add_get("/health", healthy)
    async with TestServer(health) as engine, aiohttp.ClientSession() as http:
        policy = Policy(catalog())
        policy.endpoint = lambda _: str(engine.make_url("/")).rstrip("/")
        controller = Controller(policy, daemon, http, directory)
        app = create_app(controller, TOKEN)
        if lose_response:

            @web.middleware
            async def lose_once(request, handler):
                nonlocal lose_response
                response = await handler(request)
                if lose_response and request.path == "/v1/activate":
                    lose_response = False
                    request.transport.close()
                return response

            app.middlewares.insert(0, lose_once)
        async with TestClient(TestServer(app)) as client:
            while controller.phase == "recovering":
                await asyncio.sleep(0)
            yield client, controller, daemon, http


async def activate(client, controller, model, operation_id):
    response = await client.post(
        "/v1/activate",
        json={"model": model, "operation_id": operation_id},
        headers=HEADERS,
    )
    assert response.status == 202, await response.text()
    await controller.task
    return controller.state["operations"][operation_id]


@pytest.mark.parametrize(
    "body",
    [
        {"model": "unknown", "operation_id": "x"},
        {"model": "first", "operation_id": "x", "image": "malicious"},
        {"model": "first", "operation_id": "x", "HostConfig": {"Privileged": True}},
        {"model": "first", "operation_id": "x", "gpu": "all"},
        {"model": {"command": "bad"}, "operation_id": "x"},
        {"model": "first", "operation_id": "../../other"},
    ],
)
def test_invalid_activation_never_reaches_daemon(tmp_path, body):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            before = len(daemon.calls)
            response = await client.post("/v1/activate", json=body, headers=HEADERS)
            assert response.status == 400
            assert len(daemon.calls) == before
            assert controller.phase == "idle"

    asyncio.run(scenario())


def test_authentication_before_daemon_access(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, _, daemon, _):
            before = len(daemon.calls)
            for path in ("/v1/status", "/v1/operations/x"):
                assert (await client.get(path)).status == 401
            assert (
                await client.post(
                    "/v1/activate", json={"model": "first", "operation_id": "x"}
                )
            ).status == 401
            assert len(daemon.calls) == before

    asyncio.run(scenario())


def test_failed_controller_can_deactivate_verified_resources_without_relaunch(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            await activate(client, controller, "first", "initial")
            # A failed startup recovery leaves a stopped, durably recorded engine.
            for container in daemon.containers.values():
                container["State"]["Running"] = False
            controller.state["active"] = None
            controller.phase, controller.error = "error", "startup recovery failed"
            controller.save()
            before = len(daemon.calls)
            body = {"operation_id": "stop-failed"}
            assert (await client.post("/v1/deactivate", json=body)).status == 401
            assert (
                await client.post(
                    "/v1/activate",
                    json={"operation_id": "unsafe-start", "model": "second"},
                    headers=HEADERS,
                )
            ).status == 409
            response = await client.post("/v1/deactivate", json=body, headers=HEADERS)
            assert response.status == 202
            await controller.task
            assert controller.phase == "idle" and controller.error == ""
            assert not daemon.containers and not controller.state["containers"]
            assert controller.state["last_good"] == "first"
            assert controller.state["enabled"] is False
            assert not any(
                path.endswith("/start") for _, path, _ in daemon.calls[before:]
            )

    asyncio.run(scenario())


def test_failed_controller_deactivation_still_refuses_unrecorded_resources(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            await activate(client, controller, "first", "initial")
            stray = "f" * 64
            daemon.containers[stray] = copy.deepcopy(
                next(iter(daemon.containers.values()))
            )
            controller.phase, controller.error = "error", "startup recovery failed"
            before = len(daemon.calls)
            response = await client.post(
                "/v1/deactivate", json={"operation_id": "stop-failed"}, headers=HEADERS
            )
            assert response.status == 202
            await controller.task
            assert controller.phase == "error"
            assert stray in daemon.containers
            assert not any(
                path.endswith("/stop") or method == "DELETE"
                for method, path, _ in daemon.calls[before:]
            )

    asyncio.run(scenario())


def test_switch_replay_and_stop_before_start(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            assert (await activate(client, controller, "first", "one"))[
                "state"
            ] == "succeeded"
            first = next(iter(daemon.containers))
            assert (await activate(client, controller, "second", "two"))[
                "state"
            ] == "succeeded"
            starts = [
                i
                for i, (_, path, _) in enumerate(daemon.calls)
                if path.endswith("/start")
            ]
            stop = next(
                i
                for i, (_, path, _) in enumerate(daemon.calls)
                if path == f"/containers/{first}/stop"
            )
            assert starts[0] < stop < starts[1]
            before = len(daemon.calls)
            replay = await client.post(
                "/v1/activate",
                json={"model": "second", "operation_id": "two"},
                headers=HEADERS,
            )
            assert replay.status == 200
            assert len(daemon.calls) == before
            conflict = await client.post(
                "/v1/activate",
                json={"model": "first", "operation_id": "two"},
                headers=HEADERS,
            )
            assert conflict.status == 400
            assert len(daemon.containers) == 1

    asyncio.run(scenario())


def test_failed_model_restores_previous_engine(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            await activate(client, controller, "first", "one")
            result = await activate(client, controller, "broken", "two")
            assert result["state"] == "failed"
            assert controller.phase == "ready"
            assert controller.state["active"] == "first"
            assert len(daemon.containers) == 1
            assert next(iter(daemon.containers.values()))["State"]["Running"]

    asyncio.run(scenario())


def test_conflicting_operation_is_rejected(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            gate = asyncio.Event()
            original = controller.ready

            async def not_ready(model):
                await gate.wait()
                return await original(model)

            controller.ready = not_ready
            first = await client.post(
                "/v1/activate",
                json={"model": "first", "operation_id": "one"},
                headers=HEADERS,
            )
            assert first.status == 202
            second = await client.post(
                "/v1/activate",
                json={"model": "second", "operation_id": "two"},
                headers=HEADERS,
            )
            assert second.status == 409
            gate.set()
            await controller.task
            assert len(daemon.containers) == 1

    asyncio.run(scenario())


def test_foreign_labels_cannot_authorize_mutation(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            foreign = "f" * 64
            daemon.containers[foreign] = {"Config": {"Labels": {OWNER: "unrelated"}}}
            await activate(client, controller, "first", "one")
            assert foreign in daemon.containers
            forged = "e" * 64
            daemon.containers[forged] = copy.deepcopy(
                next(c for i, c in daemon.containers.items() if i != foreign)
            )
            before = len(daemon.calls)
            result = await activate(client, controller, "second", "two")
            assert result["state"] == "failed"
            assert controller.phase == "error"
            assert all(method == "GET" for method, _, _ in daemon.calls[before:])
            assert forged in daemon.containers and foreign in daemon.containers

    asyncio.run(scenario())


def test_changed_privileges_fail_closed_without_stop(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            await activate(client, controller, "first", "one")
            next(iter(daemon.containers.values()))["HostConfig"]["Privileged"] = True
            before = len(daemon.calls)
            assert (await activate(client, controller, "second", "two"))[
                "state"
            ] == "failed"
            assert controller.phase == "error"
            assert all(method == "GET" for method, _, _ in daemon.calls[before:])

    asyncio.run(scenario())


def test_restart_resets_orphaned_work_and_keeps_last_good_model(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, http):
            await activate(client, controller, "second", "one")
            old_id = next(iter(daemon.containers))
            controller.state["operations"]["interrupted"] = {
                "id": "interrupted",
                "model": "first",
                "state": "running",
            }
            controller.save()
            await controller.close()
            recovered = Controller(controller.policy, daemon, http, tmp_path)
            try:
                await recovered.recover()
                assert recovered.phase == "ready"
                assert recovered.state["active"] == "second"
                assert old_id not in daemon.containers
                assert len(daemon.containers) == 1
                assert recovered.state["operations"]["interrupted"]["state"] == "failed"
            finally:
                await recovered.close()

    asyncio.run(scenario())


def test_only_one_controller_can_own_state_directory(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (_, controller, daemon, http):
            with pytest.raises(ValueError, match="another controller"):
                Controller(controller.policy, daemon, http, tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(gpu="all"),
        lambda c: c.update(network="host"),
        lambda c: c["models"]["first"].update(privileged=True),
        lambda c: c["models"]["first"].update(
            mounts=[{"source": "/", "target": "/host", "read_only": False}]
        ),
        lambda c: c.update(allow_local_images=False),
    ],
)
def test_invalid_operator_templates_rejected(change):
    config = catalog()
    change(config)
    with pytest.raises(ValueError):
        Policy(config)


def test_deactivation_remembers_selection_without_restarting_engine(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, http):
            await activate(client, controller, "second", "one")
            response = await client.post(
                "/v1/deactivate", json={"operation_id": "stop"}, headers=HEADERS
            )
            assert response.status == 202
            await controller.task
            assert not daemon.containers
            assert controller.state["last_good"] == "second"
            await controller.close()
            recovered = Controller(controller.policy, daemon, http, tmp_path)
            try:
                await recovered.recover()
                assert recovered.phase == "idle"
                assert recovered.state["last_good"] == "second"
                assert not daemon.containers
            finally:
                await recovered.close()

    asyncio.run(scenario())


def test_interrupted_deactivation_does_not_restart_engine(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, http):
            await activate(client, controller, "second", "one")
            controller.state["operations"]["stop"] = {
                "id": "stop",
                "model": None,
                "state": "running",
            }
            controller.save()
            await controller.close()
            recovered = Controller(controller.policy, daemon, http, tmp_path)
            try:
                await recovered.recover()
                assert recovered.phase == "idle"
                assert not daemon.containers
            finally:
                await recovered.close()

    asyncio.run(scenario())


def test_state_write_failure_prevents_docker_mutation(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            before = len(daemon.calls)

            def failed_write():
                raise OSError("disk full")

            monkeypatch.setattr(controller, "_save", failed_write)
            response = await client.post(
                "/v1/activate",
                json={"model": "first", "operation_id": "one"},
                headers=HEADERS,
            )
            assert response.status == 409
            assert controller.phase == "error"
            assert len(daemon.calls) == before

    asyncio.run(scenario())


def test_lost_activation_response_reuses_the_same_operation(tmp_path, caplog):
    caplog.set_level("INFO")

    async def scenario():
        async with setup(tmp_path, lose_response=True) as (
            client,
            controller,
            daemon,
            http,
        ):
            supervisor = ManagedSupervisor(
                str(client.make_url("/")).rstrip("/"), TOKEN, http
            )
            result = await supervisor.operation("activate", "first", 5)
            assert result["state"] == "succeeded"
            assert daemon.serial == 1
            assert len(controller.state["operations"]) == 1
            assert len(daemon.containers) == 1

    asyncio.run(scenario())

    messages = [
        json.loads(record.message)
        for record in caplog.records
        if record.name in {"engine-controller", "managed-engine"}
        and record.message.startswith("{")
    ]
    requested = next(
        item for item in messages if item["event"] == "operation.requested"
    )
    operation_id = requested["operation_id"]
    related = [item for item in messages if item.get("operation_id") == operation_id]
    assert {item["event"] for item in related} >= {
        "operation.requested",
        "operation.accepted",
        "engine.recorded",
        "engine.ready",
        "operation.finished",
        "operation.observed",
        "operation.response_unknown",
    }
    assert TOKEN not in json.dumps(messages)


def test_restart_during_loading_resets_replacement_and_restores_last_good(tmp_path):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, http):
            await activate(client, controller, "first", "one")
            loading = asyncio.Event()

            async def never_ready(_):
                loading.set()
                await asyncio.Future()

            controller.ready = never_ready
            response = await client.post(
                "/v1/activate",
                json={"model": "second", "operation_id": "two"},
                headers=HEADERS,
            )
            assert response.status == 202
            await loading.wait()
            replacement_id = next(iter(daemon.containers))
            await controller.close()
            recovered = Controller(controller.policy, daemon, http, tmp_path)
            try:
                await recovered.recover()
                assert recovered.phase == "ready"
                assert recovered.state["active"] == "first"
                assert replacement_id not in daemon.containers
                assert len(daemon.containers) == 1
                assert recovered.state["operations"]["two"]["state"] == "failed"
            finally:
                await recovered.close()

    asyncio.run(scenario())


def test_failed_rollback_remains_unavailable(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path) as (client, controller, daemon, _):
            await activate(client, controller, "first", "one")
            original = daemon.call

            async def fail_starts(method, path, **kwargs):
                if path.endswith("/start"):
                    raise ConnectionError("daemon interrupted")
                return await original(method, path, **kwargs)

            monkeypatch.setattr(daemon, "call", fail_starts)
            result = await activate(client, controller, "second", "two")
            assert result["state"] == "failed"
            assert "rollback" in result["error"]
            assert controller.phase == "error"
            assert not any(c["State"]["Running"] for c in daemon.containers.values())

    asyncio.run(scenario())


def test_different_deployments_cannot_lease_the_same_gpu(tmp_path):
    async def scenario():
        config = catalog()
        config["gpu"] = "GPU-reserved-5090"
        config["allow_local_images"] = False
        for model in config["models"].values():
            model["image"] = "sha256:" + "a" * 64
        policy = Policy(config)
        async with aiohttp.ClientSession() as http:
            first = Controller(
                policy, RecordingDocker(), http, tmp_path / "one", tmp_path / "leases"
            )
            try:
                with pytest.raises(
                    ValueError, match="another controller owns the assigned GPU"
                ):
                    Controller(
                        policy,
                        RecordingDocker(),
                        http,
                        tmp_path / "two",
                        tmp_path / "leases",
                    )
            finally:
                await first.close()
            second = Controller(
                policy, RecordingDocker(), http, tmp_path / "two", tmp_path / "leases"
            )
            await second.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["/var/run/docker.sock", "../foreign", ""])
def test_named_volume_sources_must_be_fixed_volume_names(source):
    config = catalog()
    config["models"]["first"]["mounts"] = [
        {"type": "volume", "source": source, "target": "/cache", "read_only": False}
    ]
    with pytest.raises(ValueError, match="volume name"):
        Policy(config)
