# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Runner for LightX2V, SGLang Diffusion and vLLM-Omni on livepeer-node, one process per GPU, registering two apps that share one GPU lock:
  - single-shot `video:generations/<model>`: `POST /generate` streams progress and the MP4 over Server-Sent Events;
  - persistent `video:sessions/<model>`: `POST /session/start` and `/session/jobs` render clips into trickle `video` and `events` channels.
- Per-engine model catalogs, and runtime model switching through an authenticated admin API with rollback on failure.
- Immediate refusal of busy requests (503 / 409), engine job cancellation on client disconnect, idle session release, and clean deregistration on SIGTERM.
- CPU stub engine speaking both engine APIs, reference client, unit tests and an end-to-end script.
- Docker images per engine, and compose files that build the orchestrator from a pinned livepeer-node commit.
- CI: lint, unit tests, compose validation and an end-to-end run with the stub engine.

### Fixed

- Trickle segments are sent as complete requests, and quiet session channels get keepalive segments, so sessions survive idle gaps and long renders.
- A persistent client no longer hangs when a job is refused as busy.

[Unreleased]: https://github.com/Cloud-SPE/livepeer-video-engine-runners/commits/main
