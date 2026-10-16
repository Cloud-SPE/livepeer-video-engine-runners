# Maintain catalogs and deployment inputs

The repository has separate sources for public request settings, trusted managed
launch policy, engine images and model assets. The [architecture](../../ARCHITECTURE.md#configuration-ownership)
defines their authority. The [generated reference](../reference/configuration.md)
lists public data fields and Python CLI arguments directly from source.

## Sources and generated outputs

| Edit this source                                                                                          | Purpose                                                               | Generated output                                                                                                              |
| --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `models/sglang.json`, `models/lightx2v.json`, `models/vllm-omni.json`                                     | Public IDs, request defaults, pricing and bundled/external commands   | `models/all.json`                                                                                                             |
| `configs/controller/sglang.json`, `configs/controller/lightx2v.json`, `configs/controller/vllm-omni.json` | Trusted managed launch templates                                      | `configs/controller/all.json`                                                                                                 |
| `configs/engine-images.json`                                                                              | Immutable separate-engine image references and LightX2V source commit | No generated launch policy; checked against trusted images, separate Compose image defaults and LightX2V Dockerfile arguments |
| `configs/model-assets.json`                                                                               | Asset revisions, storage layout and default preparation models        | Used directly by weight preparation and GPU validation                                                                        |
| `src/video_runners/` Python parsers, public dataclasses and controller field allowlists                   | CLI options/default expressions and accepted configuration fields     | `docs/reference/configuration.md`                                                                                             |

Do not hand-edit generated files. From the checkout:

```sh
python3 src/video_runners/tools/sync_config.py --write
git diff
scripts/check.sh
```

Without `--write`, the sync command is read-only and exits unsuccessfully for
source disagreement or stale outputs. It uses only the standard library and
starts no services. The fast checks and CI's `test` job run it in check mode.
Regeneration refuses conflicting sources before writing any output.

Public and trusted catalogs are generated independently. The trusted generator
reads only per-engine controller files; it cannot copy a command, image, mount
or other launch field from a public catalog. Its global namespace/network/GPU
headers must agree across all engine policies. Existing combined IDs receive an
engine prefix, such as `sglang-fastwan2.1-t2v-1.3b`. Order remains the first model
from each engine, then the second, in SGLang, LightX2V, vLLM-Omni order. The
combined public default is the prefixed SGLang default. Each generator includes
all entries from its own sources; cross-checking IDs does not grant authority.

## Change a model or pin

1. Edit the per-engine public catalog for request defaults, pricing or
   bundled/external settings. Review trusted launch changes separately in the
   corresponding controller catalog.
2. For a new model, add its pinned asset plan and ensure all three model-ID sets
   agree. Preparation defaults must match the corresponding public defaults.
3. For separate-engine upgrades, edit the immutable image manifest and matching
   trusted/Compose references. For LightX2V, keep Dockerfile base/source defaults
   in agreement too; preparation records the built engine's immutable local ID
   in `.engine-images.env`.
4. Regenerate, review the diff and run the [affected verification tier](../reference/checks.md#match-checks-to-the-change).
   Changing an actual engine profile requires fresh hardware evidence before
   claiming compatibility. Regenerating unchanged catalogs does not require an
   inference run.

The checker verifies full image digests and asset commits, model-ID/default
agreement, trusted model paths against prepared assets and selected checked-in
deployment defaults. CPU contracts also check managed/external command agreement.
It does not establish model availability, GPU compatibility, memory fit or paid
readiness. Legacy bundled base tags remain separately configurable; their
defaults are not claims of pinned GPU validation.

Before applying launch-policy changes to an existing deployment, deactivate its
recorded engine using the old policy as described in the
[deployment guide](container-deployment.md#stop-restart-and-update). Catalog regeneration
does not update a deployed controller or its durable state.

Asset plans may specify a nonempty `allow_patterns` list for selective snapshot
downloads. Patterns select files from the pinned base revision; `extra_files`
retain their own repository/revision pins, and `required_files` still gates
readiness. This is used by LightWan NVFP4 to avoid unused BF16 expert downloads.
Existing plans without patterns still download their full snapshots.

## Private operator settings

Keep `.env`, `.engine-images.env`, host keys and credential files outside Git.
Operator Python tools share a literal initializer-style `KEY=value` reader:
optional surrounding quotes are removed, values are never expanded or executed,
and later files override earlier ones. Recovery validation reads the selected
private env file followed by staged image references. This helper is not a full
Compose dotenv parser; use the initializer's simple format for these tools.

Shared subprocess output capture does not select containers, volumes, ownership
or retry policy. Those decisions remain explicit in each operator command.
The engine launcher and weight-preparation image remain standalone; upstream
engines do not need the host-tool helper or a runner installation.
