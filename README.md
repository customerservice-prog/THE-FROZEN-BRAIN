# THE FROZEN BRAIN

**ColdVault AI** is a local-first, model-agnostic foundation for a private, survivable AI system.

> Preserve useful machine intelligence independently of any single cloud, company, model, GPU, operating system, or device.

This repository turns the "Frozen Brain" idea into software. Model weights are the replaceable brain. ColdVault keeps the durable pieces around that brain: **identity, continuity, memory, knowledge, tools, project state, checkpoints, and recovery procedures**.

## What works now

The initial foundation includes:

- SQLite WAL event journal
- Explicit long-term memory with kind, source, confidence, and tags
- Structured belief/evidence tracking that preserves hypotheses, assumptions, support, and contradictions
- Persistent cognitive state for active project, objective, hypotheses, uncertainty, next action, and related state
- SHA-256 cognitive checkpoints that restore after restart\n- Prospective memory for future commitments with due-time persistence\n- Crash journal replay for cognitive changes made after the last checkpoint\n- Persistent tool jobs that recover interrupted work and support explicit retry\n- Local document ingestion for text, HTML, DOCX, and offline PDF extraction when archived support is present\n- Hybrid lexical + optional local semantic retrieval through a local embedding model\n- A provider adapter for a **local** OpenAI-compatible model server
- Multi-model capability routing and Deep Think deliberation with independent solvers + critic synthesis
- Permission-scoped workspace tools with path-escape protection
- CLI
- Local browser UI at port `7777`
- Streaming browser responses from local OpenAI-compatible model servers\n- Local speech-to-text and text-to-speech adapters\n- Local multimodal image/vision analysis\n- Zero required Python runtime dependencies beyond the standard library
- Offline smoke tests and recovery documentation\n- ColdVault Ark catalog with category completeness checks, SHA-256 integrity scanning, and human-readable recovery index\n- No-model/no-WAN resurrection harness in CI\n- Old-phone Android/Termux launcher with conservative GGUF selection\n
It does **not** fake missing features. Model weights are not committed, and image indexing, audio/video indexing, resumable agent jobs, signed recovery media, and Android survival mode remain roadmap phases.

## Architecture

```text
                       +----------------------+
                       |       IDENTITY       |
                       +----------+-----------+
                                  |
USER -> Browser/CLI -> COLDVAULT CORE -> LOCAL MODEL ENDPOINT -> FROZEN BRAIN
                           |   |   |
                           |   |   +---- Knowledge
                           |   +-------- Memory
                           +------------ Continuity / Checkpoints
                                  |
                                  +---- Permission-gated tools / world
```

The durable state is model-neutral. A larger server brain and a smaller survival brain can therefore operate on the same exported identity/state formats.

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design.

## Quick start

Requires Python 3.11+.

```bash
python -m coldvault.cli status
python -m coldvault.cli serve --host 127.0.0.1 --port 7777
```

Then open:

```text
http://127.0.0.1:7777
```

The UI and continuity core work even if a model endpoint is unavailable. Generation requires a locally running OpenAI-compatible model endpoint.

### Attach a local model server

Configure the local endpoint and installed model name:

```bash
export COLDVAULT_BASE_URL=http://127.0.0.1:11434/v1
export COLDVAULT_MODEL=<your-local-model-name>
```

ColdVault makes no outbound cloud call by itself. The provider URL is configurable; for a fully offline system keep it on loopback or a trusted offline LAN.

## Durable state

By default ColdVault writes runtime state to:

```text
~/.coldvault/
```

Override it with:

```bash
export COLDVAULT_HOME=/your/coldvault-data
```

Important contents include:

```text
coldvault.sqlite3   event journal, memory, checkpoint records, knowledge index
checkpoints/        portable checkpoint envelopes
knowledge/          reserved local knowledge source storage
workspace/          permission-scoped working world
logs/               local logs
```

## Memory

```bash
python -m coldvault.cli remember "Generator spark was confirmed" --kind episodic --source user
python -m coldvault.cli memory-search "generator spark"
```

Kinds currently supported:

- `episodic`
- `semantic`
- `procedural`
- `prospective`
- `preference`
- `relationship`

Memory is explicit state, not hidden inside a model.

## Continuity

```bash
python -m coldvault.cli state \
  --project "Generator repair" \
  --objective "Find why it will not start" \
  --next-action "Check fuel flow"

python -m coldvault.cli checkpoint --reason "before shutdown"
```

On the next launch the latest valid checkpoint is restored from SQLite after SHA-256 verification.

## Knowledge

v0.1 deliberately starts with a dependency-free text index:

```bash
python -m coldvault.cli ingest ./manuals/generator.md
```

The retrieval layer is replaceable. Future vector indexes are treated as rebuildable acceleration data; original source files remain authoritative.

## Tests

No online service is required:

```bash
python -m unittest discover -s tests -v
python scripts/smoke_test.py
```

## Cold-storage rule

Do **not** treat this GitHub repository as the survival archive.

A real ColdVault archive must physically store and verify:

- full source history
- model weights
- inference runtimes
- tokenizers/configurations
- operating-system installers
- drivers/firmware
- language/package dependencies
- memory database
- checkpoints
- knowledge sources
- recovery documentation
- cryptographic manifests

See [`docs/RECOVERY.md`](docs/RECOVERY.md).

## Small-device principle

ColdVault has no single minimum intelligence tier. The long-term design is:

```text
Frontier server -> workstation -> laptop/mini-PC -> modern phone -> old ARM phone
```

Losing hardware should reduce model capability, not erase identity, memory, knowledge, or current work.

## Project status

**v0.1: working continuity foundation.**

Next priority: prospective memory, crash/resume continuity, signed recovery state, deeper media indexing, and the Android survival runtime.

See [`docs/ROADMAP.md`](docs/ROADMAP.md).
\n## Old-phone survival\n\nThe first Android survival profile is documented in [`survival/android-termux/README.md`](survival/android-termux/README.md). It deliberately contains no package downloads: the phone must be restorable from the physical ColdVault Ark.\n