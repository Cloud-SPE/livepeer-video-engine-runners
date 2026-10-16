"""Video engine runner process: CLI, listeners and shutdown wiring."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from contextlib import suppress
from pathlib import Path
import aiohttp
from aiohttp import web
from video_runners.catalog import load_catalog
from video_runners.lifecycle.bundled import EngineSupervisor
from video_runners.lifecycle.external import ExternalSupervisor
from video_runners.lifecycle.managed import ManagedSupervisor
from video_runners.runner.protocol import DEFAULT_PORT, DEFAULT_ADMIN_PORT
from video_runners.runner.service import Runner
from video_runners.runner.http import (
    handle_generate,
    handle_health,
    handle_models,
    handle_session_start,
    handle_session_job,
    require_admin_token,
    handle_admin_status,
    handle_admin_model,
)

log = logging.getLogger("video-runner")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video engine Live Runner.")
    parser.add_argument(
        "--lifecycle", choices=("bundled", "external", "managed"), default="bundled"
    )
    parser.add_argument("--engine-url", default="")
    parser.add_argument("--controller-url", default="http://controller:9200")
    parser.add_argument(
        "--controller-token", default=os.environ.get("ENGINE_CONTROLLER_TOKEN", "")
    )
    parser.add_argument("--catalog", type=Path, default=Path("models/stub.json"))
    parser.add_argument(
        "--model", default="", help="Catalog id to load (default: catalog default)"
    )
    parser.add_argument("--orchestrator", default="http://localhost:8935")
    parser.add_argument(
        "--secret",
        default=os.environ.get("LIVEPEER_BOOTSTRAP_SECRET", ""),
        help="Orchestrator bootstrap secret (or LIVEPEER_BOOTSTRAP_SECRET)",
    )
    parser.add_argument("--runner-url", default=f"http://127.0.0.1:{DEFAULT_PORT}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--admin-host", default="127.0.0.1")
    parser.add_argument("--admin-port", type=int, default=DEFAULT_ADMIN_PORT)
    parser.add_argument(
        "--delivery", choices=("single-shot", "persistent", "both"), default="both"
    )
    parser.add_argument(
        "--busy",
        choices=("reject", "wait"),
        default="reject",
        help="reject: refuse requests while the GPU is busy; wait: queue them (billed)",
    )
    parser.add_argument(
        "--session-idle-timeout",
        type=float,
        default=300.0,
        help="Release a persistent session after this many idle seconds (0 = never)",
    )
    args = parser.parse_args()
    if not args.secret:
        parser.error("--secret or LIVEPEER_BOOTSTRAP_SECRET is required")
    if args.lifecycle == "external" and not args.engine_url:
        parser.error("--engine-url is required for external lifecycle")
    if args.lifecycle == "managed" and len(args.controller_token) < 32:
        parser.error("ENGINE_CONTROLLER_TOKEN must have at least 32 characters")
    return args


async def _serve(args: argparse.Namespace) -> None:
    models, default = load_catalog(args.catalog)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        supervisor = EngineSupervisor()
        if args.lifecycle == "external":
            supervisor = ExternalSupervisor(args.engine_url)
        elif args.lifecycle == "managed":
            supervisor = ManagedSupervisor(
                args.controller_url, args.controller_token, http
            )
        runner = Runner(args=args, models=models, http=http, supervisor=supervisor)
        monitor = None

        async def load_initial() -> None:
            initial_model = args.model or default
            if isinstance(supervisor, ManagedSupervisor):
                restored = await supervisor.preferred_model()
                initial_model = args.model or restored or default
            await runner.load(initial_model)

        public = web.Application(client_max_size=64 * 1024)
        public["runner"] = runner
        public.router.add_get("/healthz", handle_health)
        public.router.add_get("/models", handle_models)
        public.router.add_post("/generate", handle_generate)
        public.router.add_post("/session/start", handle_session_start)
        public.router.add_post("/session/jobs", handle_session_job)

        admin = web.Application(middlewares=[require_admin_token])
        admin["runner"] = runner
        admin["admin_token"] = os.environ.get("RUNNER_ADMIN_TOKEN", "")
        admin.router.add_get("/admin/status", handle_admin_status)
        admin.router.add_post("/admin/model", handle_admin_model)

        sites: list[web.AppRunner] = []
        try:
            for app, host, port in (
                (public, args.host, args.port),
                (admin, args.admin_host, args.admin_port),
            ):
                site_runner = web.AppRunner(app)
                await site_runner.setup()
                await web.TCPSite(site_runner, host, port).start()
                sites.append(site_runner)
            # SIGTERM (docker stop, systemd) must also stop the engine process
            # group and deregister, not just end this process.
            stopping = asyncio.Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(signum, stopping.set)
            # Register only once the engine answers: discovery should never list
            # a runner that cannot take a job yet.
            loading = asyncio.create_task(load_initial())
            stop_wait = asyncio.create_task(stopping.wait())
            await asyncio.wait(
                {loading, stop_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if loading.done():
                loading.result()
                monitor = asyncio.create_task(runner.monitor_engine())
                await stop_wait
            else:
                loading.cancel()
                with suppress(asyncio.CancelledError):
                    await loading
            log.info("shutting down")
        finally:
            if monitor is not None:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
            await runner.shutdown()
            for site_runner in sites:
                await site_runner.cleanup()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    with suppress(KeyboardInterrupt):
        asyncio.run(_serve(_parse_args()))
