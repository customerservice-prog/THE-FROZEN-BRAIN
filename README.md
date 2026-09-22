# THE FROZEN BRAIN

**ColdVault AI** — a local-first, model-agnostic foundation for a private, survivable AI system.

This repository is being built around one principle:

> Preserve useful machine intelligence independently of any single cloud, company, model, GPU, operating system, or device.

The architecture separates the **Frozen Brain** (model weights) from **Identity**, **Continuity**, **Memory**, **Knowledge**, **Tools**, and the **World** it can act in. The same system can therefore scale from a server-class model down to an emergency model on constrained hardware without losing its durable state.

## Status

Early working foundation. The repository intentionally does **not** commit model weights. Local models are attached through a provider layer and the long-term ColdVault archive is stored outside Git.

See the architecture and recovery documentation in `docs/` after the initial foundation lands.
