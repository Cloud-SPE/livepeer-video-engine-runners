# Engineering principles

These principles adapt the
[harness-engineering article](https://openai.com/index/harness-engineering/) to
this project's per-GPU runner deployments.

1. **Make decisions discoverable.** Keep a short agent map, a current architecture
   guide, task-specific operating guides and versioned execution plans. Record
   decisions needed by future contributors rather than relying on chat history.
2. **Enforce useful boundaries.** Keep Livepeer in application integration and
   Docker mutation in the controller runtime. Preserve independent public and
   trusted configuration authority. Use checks with actionable failure messages.
3. **Preserve behavior through mechanical changes.** Move code separately from
   feature or policy changes. Preserve existing command entry points, protocol
   shapes and deployment behavior while reorganizing.
4. **Distinguish evidence from expectation.** A passing CPU fixture proves its
   exercised contracts. Hardware claims need actual inference with recorded
   images, model revisions and settings. Paid signing is separate from settlement.
5. **Make validation repeatable and bounded.** Give tests their own resources,
   identify what they own and remove only those resources. Keep routine checks
   independent of Docker, GPUs, remote hosts and funded accounts.
6. **Treat ambiguity explicitly.** Fail closed when ownership or GPU idle state
   is unknown. Never automatically resubmit an uncertain generation. Preserve
   durable state and shared GPU leases.
7. **Make failures inspectable.** Report the model, operation and relevant state
   without credentials, host/account identifiers or unnecessary prompt content. Public examples use generic resources and documentation-only addresses. Keep pending validation
   and technical debt visible instead of implying broad readiness from one pass.

The article's example layout is a navigation model, not a requirement to create
every directory. Add structure when it gives code, instructions or evidence a
clear home. Payment, ownership and recovery checks remain required gates for
changes that affect those behaviors.

See [architecture](../../ARCHITECTURE.md), the [refactor plan](../plans/active/harness-refactor.md)
and [check tiers](../reference/checks.md) for the concrete application of these rules.
