# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: [Security → Report a vulnerability](https://github.com/Cloud-SPE/livepeer-video-engine-runners/security/advisories/new).

Include what is affected (file, endpoint, configuration), how to reproduce it, and the impact you expect. We aim to acknowledge reports within three business days and to agree on a fix and disclosure timeline with you. We will credit you in the advisory unless you prefer otherwise.

## Supported versions

Until 1.0, only the latest commit on `main` and the latest release receive fixes.

## Scope

In scope: the runner (`runner.py`, `engines.py`), the reference client, the stub engine, Dockerfiles, compose files and CI configuration in this repository.

Out of scope, please report upstream: livepeer-node ([livepeer/node](https://github.com/livepeer/node)), the `livepeer-gateway` SDK, and the engines themselves (LightX2V, SGLang, vLLM-Omni) and their images.

## Deployment guidance

These are the security-relevant defaults an operator must change or keep:

- **Secrets.** Change `BOOTSTRAP_SECRET` (runner registration) and `RUNNER_ADMIN_TOKEN` (model switching) from their development defaults. Prefer livepeer-node's `--bootstrap-secret-file`. An empty admin token disables the admin API.
- **Admin port (8990).** Not proxied by the orchestrator; compose publishes it on `127.0.0.1` only. Never expose it publicly.
- **Runner port (8989).** Should be reachable only by your orchestrator. Clients reach it through the orchestrator, which authenticates sessions and payments.
- **Engines.** Engines listen on `127.0.0.1` inside the runner container and are not reachable from outside it. Engine images are third-party images that run as root; treat the GPU host accordingly.
- **Untrusted input.** Prompts come from network clients. The runner bounds request size (64 KB) and prompt length (4000 characters) and validates numeric fields, but the prompt is passed to the model as is.
- **Model licenses.** Selling generation on the network may be restricted by a model's license; that is a legal rather than a technical risk, but it is the operator's responsibility.
