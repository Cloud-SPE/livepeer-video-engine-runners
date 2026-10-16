"""Private authenticated controller routes and process startup."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import aiohttp
from aiohttp import web
from video_runners.controller.policy import Policy
from video_runners.controller.docker import Docker
from video_runners.controller.service import Controller


def create_app(controller: Controller, token: str) -> web.Application:
    if len(token) < 32:
        raise ValueError("ENGINE_CONTROLLER_TOKEN must have at least 32 characters")

    @web.middleware
    async def authenticate(request: web.Request, handler):
        if request.path == "/healthz" and request.method == "GET":
            return await handler(request)
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(supplied, token):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            return await handler(request)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return web.json_response(
                {"error": "invalid request or unknown model"}, status=400
            )
        except RuntimeError:
            return web.json_response(
                {"error": "controller is busy or requires recovery"}, status=409
            )

    app = web.Application(middlewares=[authenticate], client_max_size=4096)

    async def health(_):
        return web.json_response(
            {"ok": controller.phase != "error"},
            status=503 if controller.phase == "error" else 200,
        )

    async def status(_):
        return web.json_response(
            {
                "phase": controller.phase,
                "model": controller.state["active"],
                "selected": controller.state["last_good"],
                "endpoint": (
                    controller.policy.endpoint(controller.state["active"])
                    if controller.state["active"]
                    else ""
                ),
                "error": controller.error,
            }
        )

    async def activate(request):
        body = await request.json()
        expected = (
            {"operation_id", "model"}
            if request.path == "/v1/activate"
            else {"operation_id"}
        )
        if (
            not isinstance(body, dict)
            or set(body) != expected
            or not isinstance(body["operation_id"], str)
        ):
            raise ValueError("unexpected request fields")
        model = body.get("model")
        if "model" in body and not isinstance(model, str):
            raise ValueError("model must be a catalog ID")
        operation = controller.submit(body["operation_id"], model)
        return web.json_response(
            operation, status=202 if operation["state"] == "running" else 200
        )

    async def operation(request):
        op = controller.state["operations"].get(request.match_info["id"])
        if op is None:
            raise web.HTTPNotFound()
        return web.json_response(op)

    async def startup(_):
        controller.task = asyncio.create_task(controller.recover())

    async def cleanup(_):
        await controller.close()

    app.router.add_get("/healthz", health)
    app.router.add_get("/v1/status", status)
    app.router.add_get("/v1/operations/{id}", operation)
    app.router.add_post("/v1/activate", activate)
    app.router.add_post("/v1/deactivate", activate)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


async def serve(args: argparse.Namespace) -> None:
    raw = os.path.expandvars(args.catalog.read_text())
    if "${" in raw:
        raise ValueError("unresolved environment variable in controller catalog")
    policy = Policy(json.loads(raw))
    async with aiohttp.ClientSession() as http:
        controller = Controller(
            policy, Docker(args.docker_url, http), http, args.state_dir, args.lease_dir
        )
        app = create_app(controller, os.environ.get("ENGINE_CONTROLLER_TOKEN", ""))
        runner = web.AppRunner(app)
        try:
            await runner.setup()
            await web.TCPSite(runner, args.host, args.port).start()
            stopping = asyncio.Event()
            import signal

            for signum in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(signum, stopping.set)
            await stopping.wait()
        finally:
            await runner.cleanup()
