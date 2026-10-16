# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: [Security → Report a vulnerability](https://github.com/Cloud-SPE/livepeer-video-engine-runners/security/advisories/new).

Include what is affected (file, endpoint, configuration), how to reproduce it, and the impact you expect. We aim to acknowledge reports within three business days and to agree on a fix and disclosure timeline with you. We will credit you in the advisory unless you prefer otherwise.

## Supported versions

Until 1.0, only the latest commit on `main` and the latest release receive fixes.

## Scope

In scope: the `src/video_runners/` package, runtime entry points, Dockerfiles, Compose files and CI configuration in this repository.

Out of scope, please report upstream: livepeer-node ([livepeer/node](https://github.com/livepeer/node)), the `livepeer-gateway` SDK, and the engines themselves (LightX2V, SGLang, vLLM-Omni) and their images.

## Deployment guidance

These are the security-relevant defaults an operator must change or keep:

- **Secrets.** Change `BOOTSTRAP_SECRET` (runner registration) and `RUNNER_ADMIN_TOKEN` (model switching) from their development defaults. Prefer livepeer-node's `--bootstrap-secret-file`. An empty admin token disables the admin API.
- **Admin port (8990).** Not proxied by the orchestrator; Compose publishes it on host `127.0.0.1` only. The container listener is reachable by peers on the runner's Docker networks and requires the admin token. Keep those networks private and never expose admin publicly.
- **Remote signer.** The optional node signer binds to client-host loopback and mounts existing key/password/RPC files read-only under their owner's UID/GID. Keep its state directory private and writable by that user. Rate ceilings do not enforce a cumulative budget. See the [node guide](docs/guides/node-deployment.md) and upstream authorization controls before sharing signer access.
- **Runner port (8989).** Should be reachable only by your orchestrator. Clients reach it through the orchestrator, which authenticates sessions and payments.
- **Engines.** Bundled engines listen on loopback inside the runner container. Separate engines listen on a private Docker network without published ports. Engine images are third-party images that may run as root; treat the GPU host accordingly.
- **Managed Docker access.** Only the socket proxy mounts the daemon socket. The runner and engine cannot join its private network. The controller uses an independent bearer token of at least 32 characters and binds its API only to the control network. Keep the trusted catalog read-only and restrict its host mounts and GPU UUID.
- **Proxy limits.** The pinned Tecnativa proxy uses exact API routes, but does not authorize container ownership or creation bodies. The controller checks persisted container IDs and trusted configuration before mutation. A compromised controller could misuse allowed daemon operations against unrelated workloads; a shared daemon is still a trust boundary. Use a separate daemon/account or dedicated host if that residual authority is unacceptable. Mounting the socket read-only does not make Docker operations read-only.
- **State and GPU ownership.** Preserve the external controller state volume. Unknown containers claiming its namespace require operator review. The state-directory lock prevents duplicate controllers using that state; a separate shared GPU lease volume excludes managed deployments claiming the same GPU UUID. All managed controllers on the host must use the same lease volume. These locks cannot exclude unrelated GPU applications or external engines. See the [deployment guide](docs/guides/container-deployment.md) for shutdown and recovery.
- **Untrusted input.** Prompts come from network clients. The runner bounds request size (64 KB) and prompt length (4000 characters) and validates numeric fields, but the prompt is passed to the model as is.
- **Model licenses.** Selling generation on the network may be restricted by a model's license; that is a legal rather than a technical risk, but it is the operator's responsibility.
