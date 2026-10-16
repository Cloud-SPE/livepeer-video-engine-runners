# Video quality harness and larger-model trials

## Agreed scope

Preserve every existing model, public ID, default and deployment mode. Add a small
operator benchmark alongside the existing validation tools. Best visual quality
takes priority over generation latency; generation taking minutes is acceptable.
Use a mixed prompt suite initially. The operator reviews blind moving-video
comparisons and chooses useful presets. Automated scores support that judgment.

Use the existing Python SDK, optional local node signer and provider deployment.
Keep the existing production/development Compose entry points. Model launch
authority remains in the trusted controller catalogs; benchmark data never
supplies Docker commands, mounts or launch policies.

## Sequence and completion evidence

1. Add versioned prompts/suites, deterministic plans and configuration provenance.
2. Add bounded sequential generation with durable per-job records. Resume skips
   checksum-verified completed clips and refuses unknown outcomes. A changed plan
   cannot silently reuse another run's evidence.
3. Add offline technical inspection, an explicit VBench evaluator interface and
   a blind HTML review gallery with exportable ratings. Keep evaluator packages
   separate from inference/runtime dependencies. Show missing perceptual scores
   explicitly; decoding and frame differences are not perceptual quality scores.
4. Verify CPU behavior, packaging, documentation and existing deployments.
5. Run a small 5090 baseline/pilot through the SDK. Test a memory-saving Wan A14B
   recipe early, then a LightX2V larger-model candidate if compatible. Add reusable
   profiles only with pinned assets, matching independent launch policy and fresh
   hardware evidence. Preserve the existing entries and defaults.
6. Retain videos locally until reviewed. Remove owned test deployments and private
   staging resources; preserve model/cache volumes, wallets, keys and accounting.
   Publish only generic technical summaries in this repository.

## Behavioral test list

- [x] A plan expands selected prompts, seeds and experiments reproducibly.
- [x] Invalid, duplicate or unsupported controls fail before submitting work.
- [x] Interrupted/uncertain work is never automatically generated again.
- [x] Completed evidence is checked before skipping it on resume.
- [x] Concurrent invocations cannot submit the same run twice.
- [x] Reports blind experiment identity, escape prompt content and export ratings.
- [x] Scores identify evaluator/version and distinguish missing from measured.
- [x] Existing models/defaults remain present; new profiles have matching pins.

## Resource and evidence boundaries

Suite definitions and instructions are tracked; raw videos, private provenance,
receipts and reviews live in ignored per-run artifact directories. Connections,
signer URLs and credentials are operator inputs, not benchmark fixtures. GPU and
paid work are explicit operator invocations, separate from ordinary CPU CI.
Sampling controls are recorded as requested/configured/observed where supported;
the harness must not label a requested value as confirmed engine behavior.

The provider remains one exclusive GPU per engine instance. Existing model
switching coordinates lifecycle. A lock on a client host does not reserve a
remote GPU against unrelated applications. No daemon pruning or automatic
resubmission is permitted.

## Progress

The harness and six-clip 5090 pilot are implemented. Existing models/defaults
and Compose entry points are retained. LightWan A14B NVFP4 is the one added
profile, with offline preparation and real SDK delivery at 480p and 720p. Failed
full-precision/offload recipes remain private trials, not new supported profiles.
The [dated report](../../validation/reports/video-quality-2026-10-16.md) records
workloads, measured scores, startup failures and validation limits.

Generation, resume/concurrency, score binding, blinding and review aggregation
have CPU regression coverage (192 final tests). Both managed combined-catalog and bundled CPU
integration passed, as did all 33 Compose configurations and fresh wheel
installation outside the checkout. The evaluator was built and measured all six
custom-input dimensions on all six saved clips with persistent cached assets.

Operator review remains the next phase: export preferences/usability from the
private blind gallery, then select candidates for eight-prompt screening and
held-out confirmation. No default or quality winner is promoted from one
prompt/seed. The browser UI could not be exercised in this environment; review
export behavior has automated contracts, and manual playback/export remains an
operator check. No new paid-operation claim follows from this free SDK pilot.

Owned hardware-test containers, private staging and temporary resource aliases
are removed. External models/caches, wallet/key data and reusable prepared images
remain; private review clips and evaluator results are retained.
